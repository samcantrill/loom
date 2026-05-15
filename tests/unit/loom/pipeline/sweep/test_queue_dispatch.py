"""Unit tests for queue-backed sweep submission."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import RunRequest
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepQueueDispatchStatus,
    build_dispatch_requests,
    build_queue_enqueue_request,
    enqueue_sweep_trials,
    plan_sweep,
)
from loom.provenance.models import ProvenanceCaptureOptions
from loom.queue import QueueItemStatus


class _FakeQueueService:
    def __init__(self) -> None:
        self.requests = []

    def enqueue(self, request):
        self.requests.append(request)
        if request.run_uri.endswith("trial-0001"):
            raise RuntimeError("temporary queue failure")
        return SimpleNamespace(
            queue_item_id=request.queue_item_id,
            queue_name=request.queue_name,
            run_uri=request.run_uri,
            status=QueueItemStatus.QUEUED,
            enqueued_at="2026-05-14T00:00:01Z",
            metadata=request.metadata,
        )


def test_build_queue_enqueue_request_preserves_trial_metadata() -> None:
    plan = _plan()
    dispatch_request = build_dispatch_requests(
        plan,
        requested_at="2026-05-14T00:00:00Z",
    )[0]
    run_request = RunRequest(
        config={"pipeline": {"target": "demo"}},
        run_uri=dispatch_request.run_uri,
        metadata={"caller": "unit"},
    )

    enqueue_request = build_queue_enqueue_request(
        run_request,
        dispatch_request,
        queue_name="gpu",
        adapter="fake",
        entrypoint="loom run",
    )

    assert enqueue_request.queue_item_id.startswith("sweep-")
    assert enqueue_request.run_uri == "file:///tmp/queue/trial-0001"
    assert enqueue_request.tags == {
        "sweep_id": "queue",
        "trial_id": "trial-0001",
    }
    assert enqueue_request.run_metadata["caller"] == "unit"
    metadata = enqueue_request.to_dict()["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["dispatch_request"] == dispatch_request.to_dict()
    assert enqueue_request.request["config"] == {"pipeline": {"target": "demo"}}


def test_enqueue_sweep_trials_continues_after_submission_failure(tmp_path: Path) -> None:
    plan = _plan()
    queue_service = _FakeQueueService()

    result = enqueue_sweep_trials(
        plan,
        queue_service=queue_service,
        queue_name="gpu",
        request_template=_template_request(),
        sweep_dir=str(tmp_path),
        requested_at="2026-05-14T00:00:00Z",
    )

    assert result.status is SweepQueueDispatchStatus.FAILED
    assert result.failed_count == 1
    assert result.submitted_count == 1
    assert [request.run_uri for request in queue_service.requests] == [
        "file:///tmp/queue/trial-0001",
        "file:///tmp/queue/trial-0002",
    ]


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="queue",
            run_uri_root="file:///tmp/queue",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )


def _template_request() -> RunRequest:
    return RunRequest(
        pipeline=PipelineSpec(
            stages=(
                StageSpec(
                    name="build",
                    factory=StageFactorySpec(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                    outputs={"data": OutputSpec(artifact_type="json")},
                ),
            )
        ),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )
