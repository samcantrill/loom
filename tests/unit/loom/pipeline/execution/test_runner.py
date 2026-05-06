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
    PipelineRunner,
    RunRequest,
    RunRequestError,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri, run_uri_to_path
from loom.provenance.models import ProvenanceCaptureOptions
from loom.serialization import PlainData


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
