"""Unit tests for durable direct stage-worker execution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec, ProcessContainmentOwner, StageContext
from loom.pipeline.execution import (
    StageExecutionRequest,
    StageExecutionResult,
    ExecutionFailure,
    StageWorkerRunRequest,
    StageWorkerStateError,
    create_authority_backed_serial_run_store,
    prepare_stage_attempt,
    run_stage_worker,
)
from loom.pipeline.execution.models import StageWorkerRequest
from loom.pipeline.execution.authority_adapter import AuthorityBackedSerialRunStore
from loom.pipeline.execution.lifecycle import write_run_status
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.serialization import PlainData, thaw_plain_data
from loom.serialization import json_dumps_pretty
import loom.pipeline.execution.stage_worker as stage_worker


pytestmark = pytest.mark.unit


class FakeExecutor:
    name = "fake"

    def __init__(self) -> None:
        self.request: StageExecutionRequest | None = None

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        self.request = request
        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs={
                "data": ArtifactRef(
                    artifact_id="build/data",
                    uri="file:///tmp/build-data.json",
                    artifact_type="json",
                    codec_key="json.v1",
                    producer_stage="build",
                )
            },
            failure=None,
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:02Z",
            executor_name=self.name,
            attempt=request.attempt,
            stdout_path=str(request.stdout_path),
            stderr_path=str(request.stderr_path),
            executor_metadata={"fake": True},
        )


def _spec(
    *, target: str = "tests.support.pipeline_execution_stages.JsonProducerStage"
) -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": target},
                    "config": {"value": 7},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        }
    )


def _prepared_run(
    tmp_path: Path,
    *,
    persist_plan: bool = True,
    target: str = "tests.support.pipeline_execution_stages.JsonProducerStage",
) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    spec = _spec(target=target)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=persist_plan,
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty(
            {
                "pipeline": {
                    "name": "snapshot-demo",
                    "stages": [{"name": "build"}],
                }
            }
        ),
    )
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    return store, run_uri


def _authority_prepared_run(
    tmp_path: Path,
) -> tuple[AuthorityBackedSerialRunStore, SQLitePerRunAuthorityStore, str]:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=authority,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    write_run_status(
        store,
        run_uri=run_uri,
        status=RunStatus.RUNNING,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        started_at="2020-01-01T00:00:01Z",
    )
    spec = _spec()
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty(
            {
                "pipeline": {
                    "name": "snapshot-demo",
                    "stages": [{"name": "build"}],
                }
            }
        ),
    )
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    return store, authority, run_uri


def test_run_stage_worker_infers_attempt_and_writes_only_worker_result(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    executor = FakeExecutor()

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        executor=executor,
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.attempt == 1
    assert result.executor_name == "local"
    assert result.executor_metadata == {"fake": True}
    assert (
        store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    )
    assert store.read_stage_outputs(run_uri, "build") is None
    assert store.read_stage_failure(run_uri, "build") is None
    assert store.read_stage_provenance(run_uri, "build") is None
    assert store.read_artifact_index(run_uri) == {}
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.PENDING
    assert executor.request is not None
    assert executor.request.stage.factory.target_path.endswith("JsonProducerStage")
    assert (
        executor.request.context.process_containment_owner
        is ProcessContainmentOwner.STAGE
    )
    resolved_config = cast(
        Mapping[str, object],
        thaw_plain_data(executor.request.context.resolved_config),
    )
    assert resolved_config["pipeline"] == {
        "name": "snapshot-demo",
        "stages": [{"name": "build"}],
    }


def test_resident_stage_worker_passes_containment_owner_to_stage_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    request_data = store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert request_data is not None
    captured: dict[str, object] = {}

    class CapturingStage:
        def run(self, context: object, _inputs: object) -> dict[str, ArtifactRef]:
            captured["context"] = context
            return {
                "data": cast("StageContext", context).save_artifact(
                    "data",
                    {"value": 7},
                    artifact_type="json",
                    codec_key="json.v1",
                )
            }

    monkeypatch.setattr(
        stage_worker,
        "construct_stage",
        lambda **_kwargs: CapturingStage(),
    )

    result = stage_worker.execute_resident_stage_worker_request(
        worker_request=StageWorkerRequest.from_dict(request_data),
        workspace_root=tmp_path / "resident-workspace",
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
    )

    assert result.status is StageStatus.SUCCEEDED
    assert (
        cast("StageContext", captured["context"]).process_containment_owner
        is ProcessContainmentOwner.OUTER_BOUNDARY
    )


def test_run_stage_worker_validates_authority_fencing_before_execution(
    tmp_path: Path,
) -> None:
    store, authority, run_uri = _authority_prepared_run(tmp_path)
    executor = FakeExecutor()

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        executor=executor,
    )

    assert result.status == StageStatus.SUCCEEDED
    assert executor.request is not None
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None
    assert build.active_lease is not None


def test_run_stage_worker_requires_authority_fencing_when_store_supports_validation(
    tmp_path: Path,
) -> None:
    store, authority, run_uri = _authority_prepared_run(tmp_path)
    raw = store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert raw is not None
    metadata = dict(cast(Mapping[str, PlainData], raw.get("metadata", {})))
    metadata.pop("authority_attempt", None)
    store.local_store.write_stage_worker_request(
        run_uri,
        "build",
        {**raw, "metadata": metadata},
        attempt=1,
    )
    executor = FakeExecutor()

    with pytest.raises(StageWorkerStateError, match="authority_attempt"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=executor,
        )

    assert executor.request is None
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None


def test_run_stage_worker_rejects_stale_authority_fencing_before_execution(
    tmp_path: Path,
) -> None:
    store, authority, run_uri = _authority_prepared_run(tmp_path)
    raw = store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert raw is not None
    metadata = dict(cast(Mapping[str, PlainData], raw.get("metadata", {})))
    authority_attempt = dict(
        cast(Mapping[str, PlainData], metadata["authority_attempt"])
    )
    authority_attempt["fencing_token"] = "foreign-token"
    metadata["authority_attempt"] = cast(PlainData, authority_attempt)
    store.local_store.write_stage_worker_request(
        run_uri,
        "build",
        {**raw, "metadata": metadata},
        attempt=1,
    )
    executor = FakeExecutor()

    with pytest.raises(StageWorkerStateError, match="backend lease"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=executor,
        )

    assert executor.request is None
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert build.status is StageStatus.PENDING
    assert build.latest_commit is None


def test_run_stage_worker_allows_exact_attempt(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path)

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build", attempt=1),
        executor=FakeExecutor(),
    )

    assert result.attempt == 1


def test_run_stage_worker_rejects_existing_worker_result(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path)
    run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        executor=FakeExecutor(),
    )

    with pytest.raises(StageWorkerStateError, match="already has a worker result"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=FakeExecutor(),
        )


def test_run_stage_worker_rejects_completed_status_for_inference(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:03Z",
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:02Z",
        ),
    )

    with pytest.raises(StageWorkerStateError, match="not PENDING or RUNNING"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=FakeExecutor(),
        )


def test_run_stage_worker_requires_persisted_plan(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path, persist_plan=False)

    with pytest.raises(StageWorkerStateError, match="no persisted execution plan"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=FakeExecutor(),
        )


def test_run_stage_worker_records_target_construction_failure(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(
        tmp_path, target="tests.support.pipeline_execution_stages.MissingStage"
    )

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        clock=lambda: "2020-01-01T00:00:04Z",
    )

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.failure_type == "target_construction"
    assert result.exit_code == 1
    assert (
        store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    )
