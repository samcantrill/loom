"""Unit tests for durable direct stage-worker execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec, ProcessContainmentOwner, StageContext
from loom.pipeline.execution import (
    StageExecutionRequest,
    StageExecutionResult,
    prepare_stage_attempt,
)
from loom.pipeline.execution.models import StageWorkerRequest
from loom.pipeline.execution.errors import RunRequestError
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
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


def test_worker_request_rejects_saved_selection_that_conflicts_with_demand(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    payload = store.read_stage_worker_request(run_uri, "build", attempt=1)
    assert payload is not None
    runtime = cast(dict[str, object], payload["resolved_runtime"])
    runtime["resource_selection"] = {"account_for": ["gpu"], "enforce": []}

    with pytest.raises(RunRequestError, match="conflicts"):
        StageWorkerRequest.from_dict(payload)


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


def test_native_attachment_roundtrip_is_bound_before_construction(tmp_path, monkeypatch):
    from copy import deepcopy
    from loom.fingerprints import hash_mapping
    from loom.pipeline._project_contracts import CONTRACT, CAPTURE, declaration, envelope

    store, uri = _prepared_run(tmp_path)
    wire = cast(Any, store.read_stage_worker_request(uri, "build", attempt=1))
    capture = hash_mapping({"captured": "native"})
    attachment = envelope("text-project", {"semantic_key": None,
        "payload": {"path": "/opaque/path", "location": {"root": "not-resolved"}}},
        capture=capture, node="build", original=declaration(_spec().get_stage("build")))
    wire["metadata"] = {CONTRACT: attachment, CAPTURE: capture, "arbitrary": {"untrusted": True}}
    worker = StageWorkerRequest.from_dict(wire)
    assert cast(Any, worker.to_dict()["metadata"])[CONTRACT] == attachment
    seen = []

    class Stage:
        def run(self, context, inputs):
            seen.append(context)
            return {"data": context.save_artifact("data", 7, artifact_type="json", codec_key="json.v1")}

    monkeypatch.setattr(stage_worker, "construct_stage", lambda **kwargs: Stage())
    result = stage_worker.execute_resident_stage_worker_request(
        worker_request=worker, workspace_root=tmp_path / "worker",
        process_containment_owner=ProcessContainmentOwner.OUTER_BOUNDARY,
        location_resolver=lambda value: value,
    )
    assert result.status == StageStatus.SUCCEEDED
    assert seen[0].metadata[CONTRACT] == worker.metadata[CONTRACT]
    assert CAPTURE not in seen[0].metadata and "arbitrary" not in seen[0].metadata
    for fault in ("payload", "node", "version", "missing"):
        changed = deepcopy(wire)
        if fault == "payload":
            changed["metadata"][CONTRACT]["payload"]["path"] = "/other"
        elif fault == "node":
            changed["stage_name"] = "other"
            changed["resolved_runtime"]["stage_id"] = "other"
        elif fault == "version":
            changed["metadata"][CONTRACT]["schema_version"] = 99
        else:
            changed["metadata"].pop(CONTRACT)
        with pytest.raises(RunRequestError):
            StageWorkerRequest.from_dict(changed)


@pytest.mark.parametrize("key", ["loom.project_contract", "loom.project_contracts", "loom.execution_binding", "loom.remote_recovery", "loom.recovery_binding"])
def test_public_admission_rejects_reserved_metadata_before_writes(tmp_path, key):
    store = LocalRunStore(tmp_path / "runs")
    uri = path_to_run_uri(tmp_path / "runs" / "forged")
    with pytest.raises(ValueError, match="reserved"):
        store.create_run(uri, metadata={key: {}})
    assert not store.run_uri_exists(uri)
    spec = _spec()
    plan = plan_pipeline(spec, run_uri=uri, run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(uri)), persist=False)
    with pytest.raises(ValueError, match="reserved"):
        prepare_stage_attempt(run_store=store, run_uri=uri, stage=spec.get_stage("build"),
            stage_plan=plan.ordered_stage_plans[0], metadata={key: {}})
