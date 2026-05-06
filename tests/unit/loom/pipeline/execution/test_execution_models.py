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
)
from loom.serialization import PlainData


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


def test_run_request_requires_config_or_pipeline() -> None:
    with pytest.raises(RunRequestError):
        RunRequest()


def test_run_request_accepts_direct_pipeline_spec() -> None:
    spec = _minimal_pipeline_spec()

    request = RunRequest(pipeline=spec, run_id="run1")

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

    request = RunRequest(config=config, run_id="run1")

    assert request.config == config


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

    request = RunRequest(config=config, run_id="run1")

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
        RunRequest(config=cast(Any, AlmostComposedConfig()), run_id="run1")


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
        run_id="run1",
        stage_name="build",
        attempt=1,
        failed_at="2020-01-01T00:00:00Z",
        executor="local",
        failure_type="stage_exception",
        message="boom",
        details={"path": "x"},
    )

    assert ExecutionFailure.from_dict(failure.to_dict()) == failure


def test_execution_failure_from_dict_rejects_unsupported_schema_version() -> None:
    with pytest.raises(RunRequestError, match="unsupported schema version"):
        ExecutionFailure.from_dict(
            {
                "schema_version": 999,
                "run_id": "run1",
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
                "run_id": "run1",
                "stage_name": "build",
                "attempt": 1,
                "failed_at": "2020-01-01T00:00:00Z",
                "executor": "local",
                "failure_type": "stage_exception",
                "message": "boom",
                "unexpected": "field",
            }
        )


def test_config_snapshot_inputs_validate_strings() -> None:
    with pytest.raises(RunRequestError):
        ConfigSnapshotInputs(raw=object())  # type: ignore[arg-type]
