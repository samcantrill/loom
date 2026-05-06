"""Unit tests for runner stage construction delegation."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, PipelineSpec, Stage, StageFactorySpec, StageSpec
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.execution import ConfigSnapshotInputs, PipelineRunner, RunRequest
from loom.pipeline.stores import LocalRunStore
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


def test_runner_persists_composed_config_artifact_manifest_without_resolved_snapshots(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1", metadata={"caller": "unit"})
    runner = PipelineRunner(run_store=run_store)
    config = _ComposedConfig()
    request = RunRequest(
        config=config,
        run_id="run1",
        config_snapshots=ConfigSnapshotInputs(raw="name: demo\n"),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
        ),
        metadata={"caller": "unit"},
    )

    runner._write_config_and_provenance("run1", request, config.resolved)

    config_dir = run_store.local_run_dir("run1") / "config"
    assert not (config_dir / "resolved.yaml").exists()
    assert not (config_dir / "resolved.redacted.yaml").exists()
    assert run_store.read_config_snapshot("run1", "raw") == "name: demo\n"
    assert run_store.read_composition_manifest("run1") == {
        "source_artifacts": [{"kind": "config", "path": "config.yaml"}],
        "metadata": {"artifact_safe": True},
    }
    assert run_store.read_recipe_manifest("run1") == (
        {"name": "demo", "path": "pipeline"},
    )
    assert run_store.read_run_user_metadata("run1") == {
        "caller": "unit",
        "config_provenance": {"artifact_fingerprint": "sha256:abc"},
    }


def test_runner_preserves_plain_mapping_config_as_caller_provided_snapshot(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
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
        run_id="run1",
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
        ),
    )

    runner._write_config_and_provenance("run1", request, config)

    assert run_store.read_config_snapshot("run1", "resolved") is not None
    assert run_store.read_config_snapshot("run1", "resolved_redacted") is not None
    assert run_store.read_composition_manifest("run1") is None
    assert run_store.read_recipe_manifest("run1") == ()
