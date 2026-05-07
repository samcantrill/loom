"""Unit tests for execution models."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    ConfigSnapshotInputs,
    ExecutionFailure,
    FailurePolicy,
    RunRequest,
    RunRequestError,
    StageWorkerRequest,
    StageWorkerResult,
    redact_executor_metadata,
)
from loom.pipeline.planning import (
    FingerprintContext,
    PlanSelectors,
    ResumeOptions,
    build_stage_fingerprint,
)
from loom.pipeline.runtime import RunOptions
from loom.pipeline.status import StageStatus
from loom.serialization import PlainData
from loom.artifacts import ArtifactRef


def _minimal_pipeline_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        }
    )


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="build/data",
        uri="file:///tmp/build/data.json",
        artifact_type="json",
        codec_key="json.v1",
    )


def _worker_request() -> StageWorkerRequest:
    stage = _minimal_pipeline_spec().get_stage("build")
    return StageWorkerRequest(
        schema_version=1,
        run_uri="file:///tmp/run",
        stage_name="build",
        attempt=1,
        prepared_at="2020-01-01T00:00:00Z",
        executor_name="local",
        inputs={},
        fingerprint=build_stage_fingerprint(
            stage,
            bound_inputs={},
            fingerprint_context=FingerprintContext(),
        ),
        stdout_path="/tmp/run/stages/build/logs/stdout.log",
        stderr_path="/tmp/run/stages/build/logs/stderr.log",
        traceback_path="/tmp/run/stages/build/logs/traceback.txt",
        result_path="/tmp/run/stages/build/worker_result.json",
        resolved_runtime={"stage_id": "build", "executor": "local"},
        executor_metadata={"command": ["python", "-m", "loom"]},
    )


def test_run_request_requires_config_or_pipeline() -> None:
    with pytest.raises(RunRequestError):
        RunRequest()


def test_run_request_accepts_direct_pipeline_spec() -> None:
    spec = _minimal_pipeline_spec()

    request = RunRequest(pipeline=spec, run_uri="run1")

    assert request.pipeline is spec
    assert request.config is None


def test_run_request_accepts_plain_mapping_config() -> None:
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
                    },
                ]
            }
        },
    )

    request = RunRequest(config=config, run_uri="run1")

    assert request.config == config


def test_run_request_options_are_canonical_invocation_policy() -> None:
    spec = _minimal_pipeline_spec()

    request = RunRequest(
        pipeline=spec,
        options={
            "run_uri": "file:///runs/demo",
            "selectors": {"only_stages": ["build"]},
            "resume": {"enabled": False},
        },
    )

    options = cast(RunOptions, request.options)
    assert options.run_uri == "file:///runs/demo"
    assert request.run_uri == "file:///runs/demo"
    assert request.selectors == PlanSelectors(only_stages=("build",))
    assert request.resume == ResumeOptions(enabled=False)


def test_run_request_legacy_fields_normalize_into_options() -> None:
    spec = _minimal_pipeline_spec()

    request = RunRequest(
        pipeline=spec,
        run_uri="file:///runs/demo",
        selectors=PlanSelectors(only_stages=("build",)),
        resume=ResumeOptions(enabled=False),
    )

    options = cast(RunOptions, request.options)
    assert options.run_uri == "file:///runs/demo"
    assert options.to_plan_selectors() == PlanSelectors(only_stages=("build",))
    assert options.to_resume_options() == ResumeOptions(enabled=False)


def test_run_request_rejects_conflicting_legacy_options() -> None:
    spec = _minimal_pipeline_spec()

    with pytest.raises(RunRequestError, match="run_uri conflicts"):
        RunRequest(
            pipeline=spec,
            run_uri="file:///runs/legacy",
            options={"run_uri": "file:///runs/options"},
        )


def test_run_request_accepts_duck_typed_composed_config() -> None:
    class FakeComposedConfig:
        @property
        def resolved(self) -> Mapping[str, PlainData]:
            return {"pipeline": {"stages": []}}

        @property
        def redacted(self) -> Mapping[str, PlainData]:
            return {"pipeline": {"stages": []}}

        @property
        def manifest(self) -> Mapping[str, PlainData]:
            return {"source_artifacts": []}

        @property
        def provenance(self) -> object:
            return object()

        @property
        def recipe_manifest(self) -> Sequence[Mapping[str, PlainData]]:
            return ()

    config = FakeComposedConfig()

    request = RunRequest(config=config, run_uri="run1")

    assert request.config is config


def test_run_request_requires_manifest_for_composed_config_duck_type() -> None:
    class AlmostComposedConfig:
        @property
        def resolved(self) -> Mapping[str, PlainData]:
            return {"pipeline": {"stages": []}}

        @property
        def redacted(self) -> Mapping[str, PlainData]:
            return {"pipeline": {"stages": []}}

        @property
        def provenance(self) -> object:
            return object()

        @property
        def recipe_manifest(self) -> Sequence[Mapping[str, PlainData]]:
            return ()

    with pytest.raises(RunRequestError, match="ComposedConfig or mapping"):
        RunRequest(config=cast(Any, AlmostComposedConfig()), run_uri="run1")


def test_config_snapshot_inputs_remain_explicit_user_provided_fields() -> None:
    snapshots = ConfigSnapshotInputs(
        raw="raw", overlays="overlays", cli_overrides="cli"
    )

    assert snapshots.raw == "raw"
    assert snapshots.overlays == "overlays"
    assert snapshots.cli_overrides == "cli"
    assert not hasattr(snapshots, "resolved")
    assert not hasattr(snapshots, "resolved_redacted")


def test_run_request_rejects_continue_on_failure() -> None:
    with pytest.raises(RunRequestError, match="continue-on-failure"):
        RunRequest(
            pipeline=PipelineSpec.from_config(
                {
                    "stages": [
                        {
                            "name": "build",
                            "factory": {
                                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                            },
                            "outputs": {"data": {"artifact_type": "json"}},
                        }
                    ]
                }
            ),
            failure_policy=FailurePolicy(stop_on_first_failure=False),
        )


def test_run_request_rejects_non_bool_failure_policy_mapping() -> None:
    with pytest.raises(RunRequestError, match="stop_on_first_failure"):
        RunRequest(
            pipeline=PipelineSpec.from_config(
                {
                    "stages": [
                        {
                            "name": "build",
                            "factory": {
                                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                            },
                            "outputs": {"data": {"artifact_type": "json"}},
                        }
                    ]
                }
            ),
            failure_policy={"stop_on_first_failure": "false"},  # type: ignore[arg-type]
        )


def test_execution_failure_round_trips_plain_data() -> None:
    failure = ExecutionFailure(
        schema_version=1,
        run_uri="run1",
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="stage_exception",
        message="boom",
        details={"path": "x"},
    )

    assert ExecutionFailure.from_dict(failure.to_dict()) == failure


def test_execution_failure_preserves_signal_separately_from_exit_code() -> None:
    failure = ExecutionFailure(
        schema_version=1,
        run_uri="run1",
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="subprocess",
        failure_type="executor_infrastructure",
        message="terminated",
        signal=15,
    )

    assert ExecutionFailure.from_dict(failure.to_dict()).signal == 15
    with pytest.raises(RunRequestError, match="exit_code and signal"):
        ExecutionFailure(
            schema_version=1,
            run_uri="run1",
            stage_name="build",
            attempt=1,
            failed_at="2020-01-01T00:00:00Z",
            executor="subprocess",
            failure_type="executor_infrastructure",
            message="terminated",
            exit_code=143,
            signal=15,
        )


def test_execution_failure_from_dict_rejects_unsupported_schema_version() -> None:
    with pytest.raises(RunRequestError, match="unsupported schema version"):
        ExecutionFailure.from_dict(
            {
                "schema_version": 999,
                "run_uri": "run1",
                "stage_name": "build",
                "attempt": 1,
                "failed_at": "2020-01-01T00:00:00Z",
                "executor": "local",
                "failure_type": "stage_exception",
                "message": "boom",
            }
        )


def test_execution_failure_from_dict_rejects_unknown_fields() -> None:
    with pytest.raises(RunRequestError, match="unknown field"):
        ExecutionFailure.from_dict(
            {
                "schema_version": 1,
                "run_uri": "run1",
                "stage_name": "build",
                "attempt": 1,
                "failed_at": "2020-01-01T00:00:00Z",
                "executor": "local",
                "failure_type": "stage_exception",
                "message": "boom",
                "unexpected": "field",
            }
        )


def test_stage_worker_request_round_trips_plain_data() -> None:
    request = _worker_request()

    assert StageWorkerRequest.from_dict(request.to_dict()) == request


def test_stage_worker_request_validates_runtime_identity() -> None:
    data = _worker_request().to_dict()
    data["resolved_runtime"] = {"stage_id": "other", "executor": "local"}

    with pytest.raises(RunRequestError, match="stage_id"):
        StageWorkerRequest.from_dict(data)


def test_stage_worker_result_round_trips_success() -> None:
    result = StageWorkerResult(
        schema_version=1,
        run_uri="file:///tmp/run",
        stage_name="build",
        attempt=1,
        status=StageStatus.SUCCEEDED,
        started_at="2020-01-01T00:00:00Z",
        finished_at="2020-01-01T00:00:01Z",
        executor_name="worker",
        outputs={"data": _artifact_ref()},
        exit_code=0,
    )

    assert StageWorkerResult.from_dict(result.to_dict()) == result


def test_stage_worker_result_rejects_conflicting_success_failure_metadata() -> None:
    with pytest.raises(RunRequestError, match="nonzero process failure"):
        StageWorkerResult(
            schema_version=1,
            run_uri="file:///tmp/run",
            stage_name="build",
            attempt=1,
            status=StageStatus.SUCCEEDED,
            started_at="2020-01-01T00:00:00Z",
            finished_at="2020-01-01T00:00:01Z",
            executor_name="worker",
            outputs={"data": _artifact_ref()},
            signal=15,
        )


def test_stage_worker_result_requires_failure_for_failed_status() -> None:
    with pytest.raises(RunRequestError, match="failure is required"):
        StageWorkerResult(
            schema_version=1,
            run_uri="file:///tmp/run",
            stage_name="build",
            attempt=1,
            status=StageStatus.FAILED,
            started_at="2020-01-01T00:00:00Z",
            finished_at="2020-01-01T00:00:01Z",
            executor_name="worker",
        )


def test_executor_metadata_redaction_removes_secrets_and_environment_values() -> None:
    redacted = redact_executor_metadata(
        {
            "command": ["python", "--token=abc"],
            "environment": {"TOKEN": "abc", "PATH": "/bin"},
            "nested": {"password": "secret"},
        }
    )

    assert redacted == {
        "command": ["python", "[redacted]"],
        "environment": {"key_count": 2, "keys": ["PATH", "TOKEN"]},
        "nested": {"password": "[redacted]"},
    }


def test_config_snapshot_inputs_validate_strings() -> None:
    with pytest.raises(RunRequestError):
        ConfigSnapshotInputs(raw=object())  # type: ignore[arg-type]
