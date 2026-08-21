"""Synthetic installed targets for Stage 28 activation integration tests."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext
from loom.pipeline.execution import (
    RuntimeServices,
    StageExecutionRequest,
    StageExecutionResult,
)
from loom.pipeline.event_sinks import EventSinkRegistration, EventSinkSubscription
from loom.pipeline.executors import (
    ExecutorRegistration,
    LocalExecutor,
    SubprocessExecutor,
)
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime import (
    ExecutorDescriptor,
    ResourceCapability,
    ResourceEnforcementExpectation,
    ResourceSupportLevel,
    RunOptions,
)
from loom.serialization import PlainData


class TaggedJsonCodec:
    key = "stage28.tagged-json.v1"

    def encode(
        self,
        obj: object,
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> bytes:
        del metadata
        return b"stage28:" + json.dumps(obj, sort_keys=True).encode("utf-8")

    def decode(
        self,
        data: bytes,
        *,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> object:
        del metadata
        prefix = b"stage28:"
        if not data.startswith(prefix):
            raise ValueError("stage28 codec prefix is missing")
        return json.loads(data.removeprefix(prefix).decode("utf-8"))


class Stage28ProducerStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data",
                {"value": context.stage_config.get("value", 1)},
                artifact_type="stage28-json",
                codec_key="stage28.tagged-json.v1",
            )
        }


def validate_device(entry: ResourceEntry, path: str) -> None:
    if entry.amount <= 0:
        raise ValueError(f"{path}.amount must be positive")
    marker = entry.attributes.get("marker")
    if marker is not None:
        if not isinstance(marker, str) or not marker:
            raise ValueError(f"{path}.attributes.marker must be a non-empty path")
        marker_path = Path(marker)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        with marker_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")


def filtered_event_sink() -> EventSinkRegistration:
    """Return the opt-in E2E observer without changing execution behavior."""

    marker = os.environ["LOOM_STAGE28_EVENT_SINK_MARKER"]

    def sink(event: object, context: object) -> None:
        del context
        event_type = getattr(event, "event_type")
        with Path(marker).open("a", encoding="utf-8") as handle:
            handle.write(f"{event_type}\n")

    return EventSinkRegistration(
        sink=sink,
        subscription=EventSinkSubscription(event_types=("stage.completed",)),
    )


class ProjectExecutor:
    name = "stage28-project"

    def __init__(self) -> None:
        self._delegate = LocalExecutor()

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        return self._delegate.execute(request)


def _build_project_executor(
    *,
    services: RuntimeServices,
    options: RunOptions,
) -> ProjectExecutor:
    del services, options
    return ProjectExecutor()


class ProjectSubprocessExecutor(SubprocessExecutor):
    name = "stage28-subprocess"


def _build_project_subprocess_executor(
    *,
    services: RuntimeServices,
    options: RunOptions,
) -> ProjectSubprocessExecutor:
    del options
    return ProjectSubprocessExecutor(
        worker_results=services.worker_results,
        plugin_selectors=(
            "loom.codecs:stage28.tagged-json.v1",
            "loom.resource_validators:stage28.device",
        ),
    )


PROJECT_EXECUTOR_REGISTRATION = ExecutorRegistration(
    descriptor=ExecutorDescriptor(
        name="stage28-project",
        resource_capabilities={
            "stage28.device": ResourceCapability(
                support_level=ResourceSupportLevel.SUPPORTED,
                enforcement=ResourceEnforcementExpectation.BEST_EFFORT,
            )
        },
    ),
    factory=_build_project_executor,
)

PROJECT_SUBPROCESS_EXECUTOR_REGISTRATION = ExecutorRegistration(
    descriptor=ExecutorDescriptor(
        name="stage28-subprocess",
        resource_capabilities={
            "stage28.device": ResourceCapability(
                support_level=ResourceSupportLevel.SUPPORTED,
                enforcement=ResourceEnforcementExpectation.BEST_EFFORT,
            )
        },
    ),
    factory=_build_project_subprocess_executor,
)


__all__ = [
    "PROJECT_EXECUTOR_REGISTRATION",
    "PROJECT_SUBPROCESS_EXECUTOR_REGISTRATION",
    "ProjectExecutor",
    "ProjectSubprocessExecutor",
    "Stage28ProducerStage",
    "TaggedJsonCodec",
    "filtered_event_sink",
    "validate_device",
]
