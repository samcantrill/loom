"""Unit tests for runner stage construction delegation."""

from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline import OutputSpec, Stage, StageFactorySpec, StageSpec
from loom.pipeline.context import StageContext
from loom.pipeline.errors import StageContractError
from loom.pipeline.execution import PipelineRunner
from loom.pipeline.stores import LocalRunStore
from loom.pipeline import PipelineSpec


class ConfigurableStage(Stage):
    def __init__(self, *, value: int = 0) -> None:
        self.value = value

    def run(self, context: StageContext, inputs: dict[str, ArtifactRef]) -> dict[str, ArtifactRef]:
        return {}


def _runner(tmp_path: Path) -> PipelineRunner:
    return PipelineRunner(run_store=LocalRunStore(tmp_path / "runs"))


def _stage(
    *,
    target_path: str,
    init: dict[str, object] | None = None,
) -> StageSpec:
    return StageSpec(
        name="build",
        factory=StageFactorySpec(target_path=target_path, init=init or {}),
        outputs={"data": OutputSpec(artifact_type="json")},
    )


def _spec(*, target_path: str, init: dict[str, object] | None = None) -> PipelineSpec:
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


def test_construct_stage_rejects_non_empty_init_for_prebuilt_instance(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    try:
        runner._construct_stage(
            spec=_spec(
                target_path=f"{__name__}.PREBUILT_STAGE", init={"value": 9}
            ),
            stage=_stage(
                target_path=f"{__name__}.PREBUILT_STAGE", init={"value": 9}
            ),
        )
    except StageContractError as exc:
        assert "factory.init must be empty" in str(exc)
    else:
        raise AssertionError("non-empty init for prebuilt stage must fail")
