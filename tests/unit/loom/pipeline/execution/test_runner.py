"""Unit tests for runner stage construction delegation."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, PipelineSpec, Stage, StageFactorySpec, StageSpec
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.execution import (
    ConfigSnapshotInputs,
    ParallelExecutionUnsupportedError,
    PipelineRunner,
    RunRequest,
    RunRequestError,
    StageExecutionRequest,
    StageExecutionResult,
)
from loom.pipeline.execution.authority_adapter import (
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
    path_to_run_uri,
    run_uri_to_path,
)
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
    return PipelineRunner(run_store=LocalRunStore(tmp_path / "runs"))


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


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


class _LimitedParallelCapabilityAuthority(InMemoryPerRunAuthorityStore):
    def capabilities(self) -> BackendCapabilitySet:
        return BackendCapabilitySet(
            backend_name="limited-authority",
            records=(
                BackendCapabilityRecord(
                    capability=BackendCapability.ATOMIC_TRANSITIONS,
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
    run_store = LocalRunStore(tmp_path / "runs")
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
    run_store = LocalRunStore(tmp_path / "runs")
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
                        "resources": {
                            "entries": {"cpu": {"kind": "cpu", "amount": 2}}
                        }
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


def test_runner_prepares_worker_attempt_for_subprocess_without_constructing_stage(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
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


def test_runner_rejects_dry_run_execution_request(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    with pytest.raises(RunRequestError, match="dry-run"):
        PipelineRunner(run_store=LocalRunStore(run_root)).run(
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


def test_runner_rejects_parallel_without_authority_backend(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"

    with pytest.raises(ParallelExecutionUnsupportedError) as exc_info:
        PipelineRunner(run_store=LocalRunStore(run_root)).run(_parallel_request())

    error = exc_info.value
    assert error.code == "pipeline.parallel.unsupported_backend"
    assert error.diagnostics[0]["code"] == "missing_authority_backend"
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
    assert diagnostic_codes == {"missing_capability"}
    diagnostic_details: list[Mapping[str, PlainData]] = []
    for diagnostic in error.diagnostics:
        raw_detail = diagnostic["detail"]
        assert isinstance(raw_detail, dict)
        diagnostic_details.append(raw_detail)
    assert {"capability": "stage_leases", "scope": "per_run"} in diagnostic_details
    assert not run_root.exists()


def test_runner_requires_run_uri_for_open_existing(tmp_path: Path) -> None:
    with pytest.raises(RunRequestError, match="open_existing requires run_uri"):
        PipelineRunner(run_store=LocalRunStore(tmp_path / "runs")).run(
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


def test_runner_persists_composed_config_artifact_manifest_without_resolved_snapshots(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
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
    run_store = LocalRunStore(tmp_path / "runs")
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
