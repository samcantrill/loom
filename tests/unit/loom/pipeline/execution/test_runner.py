"""Unit tests for runner stage construction delegation."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, PipelineSpec, Stage, StageFactorySpec, StageSpec
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.event_sinks import EventSinkContext, EventSinkRegistry
from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.pipeline.execution import (
    ConfigSnapshotInputs,
    ExecutionFailure,
    FailurePolicy,
    ParallelExecutionUnsupportedError,
    PipelineExecutionError,
    PipelineRunner,
    RunRequest,
    RunRequestError,
    RuntimeServices,
    StageExecutionRequest,
    StageExecutionResult,
    run_pipeline,
)
from loom.pipeline.execution.models import EXECUTION_FAILURE_SCHEMA_VERSION
import loom.pipeline.execution.services as execution_services
from loom.pipeline.execution.authority_adapter import (
    AuthorityBackedSerialRunStore,
    create_authority_backed_serial_run_store,
)
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    LocalRunStore,
    WorkspaceIdentity,
    path_to_run_uri,
    run_uri_to_path,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.provenance.models import ProvenanceCaptureOptions
from loom.serialization import PlainData
from tests.support.authority_stores import InMemoryPerRunAuthorityStore


class ConfigurableStage(Stage):
    def __init__(self, *, value: int = 0) -> None:
        self.value = value

    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        return {}


class _PlainRecord:
    def __init__(self, payload: Mapping[str, PlainData]) -> None:
        self.payload = dict(payload)

    def to_dict(self) -> dict[str, PlainData]:
        return dict(self.payload)


class _ComposedConfig:
    @property
    def resolved(self) -> Mapping[str, PlainData]:
        return {
            "pipeline": {
                "name": "demo",
                "stages": [
                    {
                        "name": "build",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                        },
                        "outputs": {"data": {"artifact_type": "json"}},
                    }
                ],
            },
            "secret": "runtime-value",
        }

    @property
    def redacted(self) -> Mapping[str, PlainData]:
        return {"pipeline": self.resolved["pipeline"], "secret": "***"}

    @property
    def manifest(self) -> _PlainRecord:
        return _PlainRecord(
            {
                "source_artifacts": [{"kind": "config", "path": "config.yaml"}],
                "metadata": {"artifact_safe": True},
            }
        )

    @property
    def provenance(self) -> _PlainRecord:
        return _PlainRecord({"artifact_fingerprint": "sha256:abc"})

    @property
    def recipe_manifest(self) -> Sequence[Mapping[str, PlainData]]:
        return ({"name": "demo", "path": "pipeline"},)


def _runner(tmp_path: Path) -> PipelineRunner:
    return PipelineRunner(run_store=_authority_run_store(tmp_path))


def _authority_run_store(tmp_path: Path) -> AuthorityBackedSerialRunStore:
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(
            clock=lambda: "2020-01-01T00:00:00Z"
        ),
    )


def _authority_run_store_with_coordination(
    tmp_path: Path,
) -> tuple[AuthorityBackedSerialRunStore, SQLiteWorkspaceCoordinationStore]:
    coordination_store = SQLiteWorkspaceCoordinationStore(
        tmp_path / "coordination.sqlite3",
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    coordination_store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(
            clock=lambda: "2020-01-01T00:00:00Z"
        ),
        workspace_coordination_store=coordination_store,
        authority_config={"backend_kind": "test_fake", "workspace_id": "workspace-1"},
    )
    return run_store, coordination_store


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def test_interrupt_after_committed_stage_success_preserves_outputs_and_cancels_run(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    registry = EventSinkRegistry()

    def interrupt_after_commit(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = context
        if event.event_type == "stage.completed":
            raise KeyboardInterrupt("interrupted after durable stage success")

    registry.register("test.interrupt", interrupt_after_commit)
    pipeline = PipelineSpec(
        stages=(
            StageSpec(
                name="build",
                factory=StageFactorySpec(
                    target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                ),
                outputs={
                    "data": OutputSpec(artifact_type="json", codec_key="json.v1")
                },
            ),
            StageSpec(
                name="downstream",
                factory=StageFactorySpec(
                    target_path="tests.support.pipeline_execution_stages.TextConsumerStage"
                ),
                inputs={"data": "build.data"},
                outputs={
                    "text": OutputSpec(artifact_type="text", codec_key="text.v1")
                },
            ),
        )
    )

    with pytest.raises(KeyboardInterrupt, match="after durable stage success"):
        PipelineRunner(run_store=run_store).run(
            RunRequest(
                pipeline=pipeline,
                run_uri=run_uri,
                event_sink_registry=registry,
            )
        )

    assert run_store.read_run_status(run_uri).status is RunStatus.CANCELLED
    assert run_store.read_stage_status(run_uri, "build").status is StageStatus.SUCCEEDED
    assert run_store.read_stage_status(run_uri, "downstream").status is StageStatus.BLOCKED
    outputs = run_store.read_stage_outputs(run_uri, "build")
    assert outputs is not None and set(outputs) == {"data"}
    assert run_store.read_artifact_index(run_uri) == {"build.data": outputs["data"]}


def test_runner_accepts_explicit_runtime_services(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)
    services = RuntimeServices.from_legacy(run_store)

    runner = PipelineRunner(services=services)

    assert runner.services is services
    assert runner.services.local_paths is run_store


def _facet(protocol: type[object], target: object) -> Any:
    class Facet(protocol):  # type: ignore[misc, valid-type]
        def __init__(self, target: object) -> None:
            self._target = target

        def __getattribute__(self, name: str) -> object:
            if name.startswith("_"):
                return object.__getattribute__(self, name)
            return getattr(object.__getattribute__(self, "_target"), name)

    return Facet(target)


def test_runner_accepts_split_nonlegacy_runtime_services(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)
    service_fields = {
        "lifecycle": execution_services.RunLifecycleStore,
        "documents": execution_services.RunDocumentStore,
        "freshness": execution_services.RunFreshnessStore,
        "run_status": execution_services.RunStatusStore,
        "plans": execution_services.RunPlanStore,
        "prepared_runs": execution_services.RunPreparedRunStore,
        "artifact_index": execution_services.RunArtifactIndexStore,
        "config": execution_services.RunConfigStore,
        "provenance": execution_services.RunProvenanceStore,
        "events": execution_services.RunEventStore,
        "event_sink_failures": execution_services.RunEventSinkFailureStore,
        "event_observer_links": execution_services.RunEventObserverLinkStore,
        "locks": execution_services.RunLockStore,
        "inspection": execution_services.RunInspectionStore,
        "runtime_metadata": execution_services.RunRuntimeMetadataStore,
        "submitted_operations": execution_services.RunSubmittedOperationStore,
        "reliability": execution_services.RunReliabilityStore,
        "stage_state": execution_services.StageStateStore,
        "stage_logs": execution_services.StageLogStore,
        "stage_workspaces": execution_services.StageWorkspaceStore,
        "worker_results": execution_services.StageWorkerResultStore,
        "local_paths": execution_services.LocalRunStorePaths,
    }
    service_values: dict[str, Any] = {
        name: _facet(protocol, run_store) for name, protocol in service_fields.items()
    }
    service_values["authority_store"] = run_store.authority_store
    services = RuntimeServices(**service_values)

    runner = PipelineRunner(services=services)
    runner._create_or_open_run(
        _run_uri(tmp_path),
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            )
        ),
    )

    assert not isinstance(services.lifecycle, execution_services.LegacyRunStore)
    assert run_store.read_run_status(_run_uri(tmp_path)) is not None
    assert cast(Any, runner.run_store).authority_config() is None


def test_runtime_store_facade_routes_replaced_lifecycle_facet(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)
    calls: list[str] = []

    class LifecycleReplacement:
        def create_run(self, run_uri: str, **kwargs: object) -> None:
            cast(Any, run_store.create_run)(run_uri, **kwargs)

        def open_run(self, run_uri: str) -> object:
            return run_store.open_run(run_uri)

        def resolve_run_uri(self, run_uri: str) -> str:
            return run_store.resolve_run_uri(run_uri)

        def allocate_run_uri(self) -> str:
            calls.append("allocate")
            return "file:///replacement"

    services = replace(
        RuntimeServices.from_legacy(run_store), lifecycle=LifecycleReplacement()
    )

    assert execution_services.runtime_store_facade(services).allocate_run_uri() == "file:///replacement"
    assert calls == ["allocate"]


class TrackingExecutor:
    name = "local"

    def __init__(self) -> None:
        self.requests: list[StageExecutionRequest] = []
        self._delegate = LocalExecutor()

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        self.requests.append(request)
        return self._delegate.execute(request)


class PreparedWorkerExecutor:
    name = "subprocess"
    requires_prepared_worker_request = True

    def __init__(self) -> None:
        self.requests: list[StageExecutionRequest] = []

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        self.requests.append(request)
        ref = request.context.save_artifact(
            "data",
            {"value": 99},
            artifact_type="json",
            codec_key="json.v1",
        )
        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs={"data": ref},
            failure=None,
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:02Z",
            executor_name=self.name,
            attempt=request.attempt,
            stdout_path=str(request.stdout_path),
            stderr_path=str(request.stderr_path),
            executor_metadata={"fake_subprocess": True},
        )


class RetrySequenceExecutor:
    name = "local"

    def __init__(
        self,
        *,
        failures_before_success: int,
        failure_type: str = "stage_exception",
    ) -> None:
        self.failures_before_success = failures_before_success
        self.failure_type = failure_type
        self.requests: list[StageExecutionRequest] = []

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        self.requests.append(request)
        if len(self.requests) <= self.failures_before_success:
            failure = ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_uri=request.run_uri,
                stage_name=request.stage.name,
                attempt=request.attempt,
                failed_at=f"2020-01-01T00:00:0{request.attempt + 1}Z",
                executor=self.name,
                failure_type=self.failure_type,
                message=f"{self.failure_type} on attempt {request.attempt}",
            )
            return StageExecutionResult(
                stage_name=request.stage.name,
                status=StageStatus.FAILED,
                outputs={},
                failure=failure,
                started_at=f"2020-01-01T00:00:0{request.attempt}Z",
                finished_at=failure.failed_at,
                executor_name=self.name,
                attempt=request.attempt,
            )
        ref = request.context.save_artifact(
            "data",
            {"attempt": request.attempt},
            artifact_type="json",
            codec_key="json.v1",
        )
        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs={"data": ref},
            failure=None,
            started_at=f"2020-01-01T00:00:0{request.attempt}Z",
            finished_at=f"2020-01-01T00:00:0{request.attempt + 1}Z",
            executor_name=self.name,
            attempt=request.attempt,
        )


class _LimitedParallelCapabilityAuthority(InMemoryPerRunAuthorityStore):
    def capabilities(self) -> BackendCapabilitySet:
        return BackendCapabilitySet(
            backend_name="limited-authority",
            records=(
                BackendCapabilityRecord(
                    capability=BackendCapability.RUN_ADMISSION,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.ATOMIC_TRANSITIONS,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.REVISIONED_SNAPSHOTS,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.MONOTONIC_REVISIONS,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.ATTEMPT_ALLOCATION,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.LEASE_TTL,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.FENCING_TOKENS,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.ATOMIC_OUTPUT_COMMIT,
                    scope=CapabilityScope.PER_RUN,
                ),
                BackendCapabilityRecord(
                    capability=BackendCapability.RECOVERY_SCANS,
                    scope=CapabilityScope.PER_RUN,
                ),
            ),
        )


def _stage(
    *,
    target_path: str,
    init: Mapping[str, PlainData] | None = None,
) -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(target_path=target_path, init=init or {}),
        outputs={"data": OutputSpec(artifact_type="json")},
    )


def _spec(
    *,
    target_path: str,
    init: Mapping[str, PlainData] | None = None,
) -> PipelineSpec:
    return PipelineSpec(stages=(_stage(target_path=target_path, init=init),))


def _parallel_request() -> RunRequest:
    return RunRequest(
        pipeline=PipelineSpec(
            stages=(
                _stage(
                    target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                ),
            )
        ),
        options={
            "execution": {
                "settings": {
                    "max_parallel_stages": 2,
                }
            }
        },
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def test_construct_stage_delegates_to_factory_class_with_init(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    stage = runner._construct_stage(
        spec=_spec(target_path=f"{__name__}.ConfigurableStage", init={"value": 7}),
        stage=_stage(target_path=f"{__name__}.ConfigurableStage", init={"value": 7}),
    )

    assert isinstance(stage, ConfigurableStage)
    assert stage.value == 7


def test_construct_stage_delegates_to_factory_callable(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    target_path = f"{__name__}.make_stage"
    stage = runner._construct_stage(
        spec=_spec(target_path=target_path, init={"value": 3}),
        stage=_stage(target_path=target_path, init={"value": 3}),
    )

    assert isinstance(stage, ConfigurableStage)
    assert stage.value == 3


class _prebuilt(ConfigurableStage):
    pass


PREBUILT_STAGE = _prebuilt(value=5)


def make_stage(*, value: int) -> ConfigurableStage:
    return ConfigurableStage(value=value)


def test_construct_stage_rejects_non_empty_init_for_prebuilt_instance(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path)

    try:
        runner._construct_stage(
            spec=_spec(target_path=f"{__name__}.PREBUILT_STAGE", init={"value": 9}),
            stage=_stage(target_path=f"{__name__}.PREBUILT_STAGE", init={"value": 9}),
        )
    except StageContractError as exc:
        assert "factory.init must be empty" in str(exc)
    else:
        raise AssertionError("non-empty init for prebuilt stage must fail")


def test_runner_allocates_default_run_uri_under_store_root(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
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
    )

    run_path = run_uri_to_path(result.run_uri)
    assert run_path.parent == (tmp_path / "runs").resolve()
    assert (run_path / "run.json").is_file()
    assert run_store.read_run_document(result.run_uri)["run_uri"] == result.run_uri
    runtime_metadata = run_store.read_runtime_metadata(result.run_uri)
    assert runtime_metadata is not None
    assert runtime_metadata["run_uri"] == result.run_uri
    assert runtime_metadata["executor"] == "local"
    stages = cast(Mapping[str, PlainData], runtime_metadata["stages"])
    assert set(stages) == {"build"}


def test_runner_passes_resolved_runtime_to_stage_execution_request(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = TrackingExecutor()
    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={
                "executor": "local",
                "stage_options": {
                    "build": {
                        "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 2}}}
                    }
                },
            },
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status is not None
    assert len(executor.requests) == 1
    resolved = cast(ResolvedStageRuntimeOptions, executor.requests[0].resolved_runtime)
    assert resolved.stage_id == "build"
    assert resolved.executor == "local"
    runtime_metadata = run_store.read_runtime_metadata(result.run_uri)
    assert runtime_metadata is not None
    stages = cast(Mapping[str, PlainData], runtime_metadata["stages"])
    stage_metadata = cast(Mapping[str, PlainData], stages["build"])
    resources = cast(Mapping[str, PlainData], stage_metadata["resources"])
    entries = cast(Mapping[str, PlainData], resources["entries"])
    cpu = cast(Mapping[str, PlainData], entries["cpu"])
    assert cpu["amount"] == 2
    policy_facts = run_store.list_reliability_policy_facts(
        result.run_uri,
        stage_name="build",
    )
    assert len(policy_facts) == 1
    assert policy_facts[0].to_dict()["policy"] == {
        "retry": {"enabled": False, "max_attempts": 1}
    }


def test_runner_acquires_and_releases_stage_resource_admission(
    tmp_path: Path,
) -> None:
    run_store, coordination_store = _authority_run_store_with_coordination(tmp_path)
    coordination_store.set_resource_limit("workspace-1", "cpu", limit=1)
    executor = TrackingExecutor()

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={
                "stage_options": {
                    "build": {
                        "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 1}}}
                    }
                },
            },
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert len(executor.requests) == 1
    counter = coordination_store.set_resource_limit("workspace-1", "cpu", limit=1)
    assert counter.value == 0


def test_runner_fails_fast_when_stage_resources_are_unavailable(
    tmp_path: Path,
) -> None:
    run_store, coordination_store = _authority_run_store_with_coordination(tmp_path)
    coordination_store.set_resource_limit("workspace-1", "cpu", limit=1)
    coordination_store.acquire_resource_lease(
        "workspace-1",
        "cpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )
    executor = TrackingExecutor()

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={
                "stage_options": {
                    "build": {
                        "resources": {"entries": {"cpu": {"kind": "cpu", "amount": 1}}}
                    }
                },
            },
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    failed = result.stage_results["build"]
    assert result.status == RunStatus.FAILED
    assert failed.status == StageStatus.FAILED
    assert failed.failure is not None
    assert failed.failure.failure_type == "resource_admission"
    assert failed.failure.exception_type is not None
    assert failed.failure.exception_type.endswith("ResourceAdmissionError")
    assert failed.failure.details["code"] == "resource_admission.rejected"
    assert failed.failure.details["context"] != {}
    assert executor.requests == []


def test_runner_maps_context_stop_early_to_cancelled_lifecycle(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.EarlyStopStage"
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
    )

    stage_result = result.stage_results["build"]
    run_status = run_store.read_run_status(result.run_uri)
    stage_status = run_store.read_stage_status(result.run_uri, "build")

    assert result.status == RunStatus.CANCELLED
    assert result.failure is None
    assert stage_result.status == StageStatus.CANCELLED
    assert run_status is not None
    assert run_status.status == RunStatus.CANCELLED
    assert run_status.metadata["reason_code"] == "early_stop"
    assert stage_status is not None
    assert stage_status.status == StageStatus.CANCELLED
    assert stage_status.metadata["reason_code"] == "early_stop"
    reason = cast(Mapping[str, PlainData], stage_status.metadata["reason"])
    assert reason["message"] == "stopped early"


def test_runner_prepares_worker_attempt_for_subprocess_without_constructing_stage(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = PreparedWorkerExecutor()

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.MissingStage"
                    ),
                )
            ),
            options={"executor": "subprocess"},
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert len(executor.requests) == 1
    exec_request = executor.requests[0]
    assert exec_request.stage.factory.target_path.endswith("MissingStage")
    assert exec_request.context.metadata["worker_request"] is True
    assert exec_request.resolved_runtime is not None
    raw_request = run_store.read_stage_worker_request(
        result.run_uri,
        "build",
        attempt=1,
    )
    assert raw_request is not None
    assert raw_request["executor_name"] == "subprocess"
    status = run_store.read_stage_status(result.run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.SUCCEEDED
    provenance = run_store.read_stage_provenance(result.run_uri, "build")
    assert provenance is not None
    assert provenance["executor_metadata"] == {"fake_subprocess": True}


def test_runner_retries_allowed_failure_after_persisting_decision(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = RetrySequenceExecutor(failures_before_success=1)

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={"reliability": {"retry": {"enabled": True, "max_attempts": 2}}},
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert [request.attempt for request in executor.requests] == [1, 2]
    stage_result = result.stage_results["build"]
    assert stage_result.status == StageStatus.SUCCEEDED
    assert stage_result.attempt == 2
    decisions = run_store.list_retry_decisions(result.run_uri, stage_name="build")
    assert len(decisions) == 1
    assert decisions[0].decision_reason == "retry.allowed"
    assert decisions[0].should_retry is True
    assert decisions[0].next_attempt == 2
    assert decisions[0].attempt_count == 1


def test_runner_records_disabled_retry_decision_without_retrying(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = RetrySequenceExecutor(failures_before_success=1)

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
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
    )

    assert result.status == RunStatus.FAILED
    assert [request.attempt for request in executor.requests] == [1]
    decisions = run_store.list_retry_decisions(result.run_uri, stage_name="build")
    assert len(decisions) == 1
    assert decisions[0].decision_reason == "retry.disabled"
    assert decisions[0].should_retry is False
    assert decisions[0].next_attempt is None


def test_runner_records_exhausted_retry_decision_on_final_attempt(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = RetrySequenceExecutor(failures_before_success=3)

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={"reliability": {"retry": {"enabled": True, "max_attempts": 2}}},
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.FAILED
    assert [request.attempt for request in executor.requests] == [1, 2]
    decisions = run_store.list_retry_decisions(result.run_uri, stage_name="build")
    assert [decision.decision_reason for decision in decisions] == [
        "retry.allowed",
        "retry.max_attempts_exhausted",
    ]
    assert [decision.should_retry for decision in decisions] == [True, False]
    assert decisions[-1].next_attempt is None


def test_runner_does_not_retry_non_retriable_failure_type(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)
    executor = RetrySequenceExecutor(
        failures_before_success=1,
        failure_type="stage_contract",
    )

    result = PipelineRunner(run_store=run_store, executor=executor).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
                )
            ),
            options={"reliability": {"retry": {"enabled": True, "max_attempts": 2}}},
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.FAILED
    assert [request.attempt for request in executor.requests] == [1]
    decisions = run_store.list_retry_decisions(result.run_uri, stage_name="build")
    assert len(decisions) == 1
    assert decisions[0].decision_reason == "retry.non_retriable_failure"
    assert decisions[0].failure.retriable is False


def test_runner_records_cancelled_retry_denial(tmp_path: Path) -> None:
    run_store = _authority_run_store(tmp_path)

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            pipeline=PipelineSpec(
                stages=(
                    _stage(
                        target_path="tests.support.pipeline_execution_stages.EarlyStopStage"
                    ),
                )
            ),
            options={"reliability": {"retry": {"enabled": True, "max_attempts": 2}}},
            provenance_options=ProvenanceCaptureOptions(
                capture_git=False,
                capture_environment=False,
                capture_dependencies=False,
                capture_command=False,
            ),
        )
    )

    assert result.status == RunStatus.CANCELLED
    decisions = run_store.list_retry_decisions(result.run_uri, stage_name="build")
    assert len(decisions) == 1
    assert decisions[0].decision_reason == "retry.cancelled"
    assert decisions[0].should_retry is False
    assert decisions[0].failure.reason_code == "stage.cancelled"


def test_runner_rejects_dry_run_execution_request(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    with pytest.raises(RunRequestError, match="dry-run"):
        PipelineRunner(run_store=_authority_run_store(tmp_path)).run(
            RunRequest(
                pipeline=PipelineSpec(
                    stages=(
                        _stage(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                    )
                ),
                options={"dry_run": True},
            )
        )
    assert not run_root.exists()


def test_runner_rejects_local_run_store_before_mutation(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"

    with pytest.raises(PipelineExecutionError) as exc_info:
        PipelineRunner(run_store=LocalRunStore(run_root))

    assert "authority-backed runtime store" in str(exc_info.value)
    assert "create_authority_backed_serial_run_store" in str(exc_info.value)
    assert not run_root.exists()


def test_run_pipeline_rejects_local_run_store_before_mutation(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"

    with pytest.raises(PipelineExecutionError) as exc_info:
        run_pipeline(
            RunRequest(
                pipeline=PipelineSpec(
                    stages=(
                        _stage(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                    )
                ),
            ),
            run_store=LocalRunStore(run_root),
        )

    assert "authority-backed runtime store" in str(exc_info.value)
    assert not run_root.exists()


def test_runner_rejects_continue_independent_without_bounded_parallelism(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    request = RunRequest(
        pipeline=PipelineSpec(
            stages=(
                _stage(
                    target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                ),
            )
        ),
        options={"execution": {"settings": {"failure_policy": "continue_independent"}}},
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )

    with pytest.raises(ParallelExecutionUnsupportedError) as exc_info:
        PipelineRunner(run_store=_authority_run_store(tmp_path)).run(request)

    error = exc_info.value
    assert error.code == "pipeline.parallel.failure_policy_requires_parallelism"
    assert error.context == {
        "failure_policy": "continue_independent",
        "max_parallel_stages": 1,
    }
    assert not run_root.exists()


def test_runner_rejects_legacy_continue_failure_policy_without_parallelism(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    request = RunRequest(
        pipeline=PipelineSpec(
            stages=(
                _stage(
                    target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                ),
            )
        ),
        options={"execution": {"settings": {"max_parallel_stages": 1}}},
        failure_policy=FailurePolicy(stop_on_first_failure=False),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )

    with pytest.raises(ParallelExecutionUnsupportedError) as exc_info:
        PipelineRunner(run_store=_authority_run_store(tmp_path)).run(request)

    assert (
        exc_info.value.code == "pipeline.parallel.failure_policy_requires_parallelism"
    )
    assert not run_root.exists()


def test_runner_rejects_parallel_with_unsafe_local_capture(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    run_store = create_authority_backed_serial_run_store(
        run_root,
        authority_store=InMemoryPerRunAuthorityStore(),
    )

    with pytest.raises(ParallelExecutionUnsupportedError) as exc_info:
        PipelineRunner(
            run_store=run_store,
            executor=LocalExecutor(capture_stdout_stderr=True),
        ).run(_parallel_request())

    assert exc_info.value.code == "pipeline.parallel.unsupported_executor_capture"
    assert not run_root.exists()


def test_runner_rejects_parallel_when_backend_capabilities_are_missing(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store = create_authority_backed_serial_run_store(
        run_root,
        authority_store=_LimitedParallelCapabilityAuthority(),
    )

    with pytest.raises(ParallelExecutionUnsupportedError) as exc_info:
        PipelineRunner(run_store=run_store).run(_parallel_request())

    error = exc_info.value
    assert error.code == "pipeline.parallel.unsupported_backend"
    diagnostic_codes = {str(diagnostic["code"]) for diagnostic in error.diagnostics}
    assert diagnostic_codes == {"authority.unsupported_capability"}
    diagnostic_details: list[Mapping[str, PlainData]] = []
    for diagnostic in error.diagnostics:
        raw_detail = diagnostic["detail"]
        assert isinstance(raw_detail, dict)
        diagnostic_details.append(raw_detail)
    assert {
        "missing_capability": "stage_leases",
        "scope": "per_run",
    } in diagnostic_details
    assert not run_root.exists()


def test_runner_requires_run_uri_for_open_existing(tmp_path: Path) -> None:
    with pytest.raises(RunRequestError, match="open_existing requires run_uri"):
        PipelineRunner(run_store=_authority_run_store(tmp_path)).run(
            RunRequest(
                pipeline=PipelineSpec(
                    stages=(
                        _stage(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                    )
                ),
                open_existing=True,
            )
        )


def test_runner_marks_fresh_preparation_failure_without_created_reset(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)

    def failing_artifact_store(_root: Path):
        raise RuntimeError("artifact setup failed")

    with pytest.raises(RuntimeError, match="artifact setup failed"):
        PipelineRunner(
            run_store=run_store, artifact_store_factory=failing_artifact_store
        ).run(
            RunRequest(
                pipeline=PipelineSpec(
                    stages=(
                        _stage(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                    )
                )
            )
        )

    run_uri = next(run_store.local_store.root.glob("*"))
    status = run_store.read_run_status(run_uri.as_uri())
    assert status is not None
    assert status.status is RunStatus.FAILED
    assert status.metadata == {
        "failure_phase": "preparation",
        "error_type": "RuntimeError",
    }
    events = run_store.read_events(run_uri.as_uri())
    assert events[-1].event_type == "run.preparation_failed"
    assert events[-1].payload == {
        "prior_status": "CREATED",
        "error_type": "RuntimeError",
        "message": "artifact setup failed",
    }


def test_runner_preserves_terminal_status_when_existing_preparation_fails(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    run_store.authority_store.transition_run(
        run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING
    )
    run_store.authority_store.transition_run(
        run_uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED
    )

    def failing_artifact_store(_root: Path):
        raise RuntimeError("artifact setup failed")

    with pytest.raises(RuntimeError, match="artifact setup failed"):
        PipelineRunner(
            run_store=run_store, artifact_store_factory=failing_artifact_store
        ).run(
            RunRequest(
                pipeline=PipelineSpec(
                    stages=(
                        _stage(
                            target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                        ),
                    )
                ),
                run_uri=run_uri,
                open_existing=True,
            )
        )

    assert run_store.authority_store.open_run(run_uri).status is RunStatus.SUCCEEDED


def test_runner_persists_composed_config_artifact_manifest_without_resolved_snapshots(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri, metadata={"caller": "unit"})
    runner = PipelineRunner(run_store=run_store)
    config = _ComposedConfig()
    request = RunRequest(
        config=config,
        run_uri=run_uri,
        config_snapshots=ConfigSnapshotInputs(raw="name: demo\n"),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
        ),
        metadata={"caller": "unit"},
    )

    runner._write_config_and_provenance(run_uri, request, config.resolved)

    config_dir = run_store.local_run_dir(run_uri) / "config"
    assert not (config_dir / "resolved.yaml").exists()
    assert not (config_dir / "resolved.redacted.yaml").exists()
    assert run_store.read_config_snapshot(run_uri, "raw") == "name: demo\n"
    assert run_store.read_composition_manifest(run_uri) == {
        "source_artifacts": [{"kind": "config", "path": "config.yaml"}],
        "metadata": {"artifact_safe": True},
    }
    assert run_store.read_recipe_manifest(run_uri) == (
        {"name": "demo", "path": "pipeline"},
    )
    assert run_store.read_run_user_metadata(run_uri) == {
        "caller": "unit",
        "config_provenance": {"artifact_fingerprint": "sha256:abc"},
    }


def test_runner_preserves_plain_mapping_config_as_caller_provided_snapshot(
    tmp_path: Path,
) -> None:
    run_store = _authority_run_store(tmp_path)
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    runner = PipelineRunner(run_store=run_store)
    config = cast(
        Mapping[str, PlainData],
        {
            "pipeline": {
                "stages": [
                    {
                        "name": "build",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                        },
                        "outputs": {"data": {"artifact_type": "json"}},
                    }
                ],
            }
        },
    )
    request = RunRequest(
        config=config,
        run_uri=run_uri,
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
        ),
    )

    runner._write_config_and_provenance(run_uri, request, config)

    assert run_store.read_config_snapshot(run_uri, "resolved") is not None
    assert run_store.read_config_snapshot(run_uri, "resolved_redacted") is not None
    assert run_store.read_composition_manifest(run_uri) is None
    assert run_store.read_recipe_manifest(run_uri) == ()
