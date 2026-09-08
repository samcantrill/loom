"""Unit tests for pipeline-owned stage construction helpers."""

from collections.abc import Mapping
from pathlib import Path
import sys

import pytest

from loom.pipeline import StageFactorySpec
from loom.pipeline.errors import StageContractError
from loom.pipeline.stage import Stage
from loom.pipeline.stage_factory import construct_stage, import_stage_target
from loom.pipeline.context import StageContext
from loom.artifacts import ArtifactRef


class InitStage:
    def __init__(self, *, value: int = 0) -> None:
        self.value = value

    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        _ = context, inputs
        return {}


def callable_stage_factory(*, value: int = 0) -> Stage:
    return InitStage(value=value)


class IncompleteStage:
    pass


PREINSTANTIATED_STAGE = InitStage(value=42)


def test_import_stage_target_supports_dotted_and_colon_paths() -> None:
    assert isinstance(
        import_stage_target(
            target_path="tests.unit.loom.pipeline.test_stage_factory.InitStage",
            path="$.pipeline.stages[0]",
        ),
        type,
    )
    assert isinstance(
        import_stage_target(
            target_path="tests.unit.loom.pipeline.test_stage_factory:InitStage",
            path="$.pipeline.stages[0]",
        ),
        type,
    )


def test_construct_stage_invokes_constructor_with_init_kwargs() -> None:
    stage = construct_stage(
        stage_path="$.pipeline.stages[0]",
        factory=StageFactorySpec(
            target_path=f"{__name__}.InitStage",
            init={"value": 7},
        ),
    )

    assert isinstance(stage, Stage)
    assert type(stage).__name__ == "InitStage"
    assert cast_init_value(stage) == 7


def test_construct_stage_calls_callables_with_init_kwargs() -> None:
    stage = construct_stage(
        stage_path="$.pipeline.stages[0]",
        factory=StageFactorySpec(
            target_path=f"{__name__}.callable_stage_factory",
            init={"value": 9},
        ),
    )

    assert type(stage).__name__ == "InitStage"
    assert cast_init_value(stage) == 9


def test_construct_stage_accepts_stage_instances_when_init_is_empty() -> None:
    stage = construct_stage(
        stage_path="$.pipeline.stages[0]",
        factory=StageFactorySpec(
            target_path=f"{__name__}:PREINSTANTIATED_STAGE",
        ),
    )

    assert stage is PREINSTANTIATED_STAGE


def test_construct_stage_rejects_instance_with_non_empty_init() -> None:
    with pytest.raises(
        StageContractError,
        match="must be empty when the stage target is an instance",
    ):
        construct_stage(
            stage_path="$.pipeline.stages[0]",
            factory=StageFactorySpec(
                target_path="tests.unit.loom.pipeline.test_stage_factory:PREINSTANTIATED_STAGE",
                init={"value": 1},
            ),
        )


def test_construct_stage_rejects_invalid_path_syntax() -> None:
    with pytest.raises(StageContractError, match="required"):
        import_stage_target(target_path="invalid", path="$.pipeline.stages[0]")


def test_construct_stage_rejects_protocol_mismatch() -> None:
    with pytest.raises(
        StageContractError, match="did not construct a Stage-compatible object"
    ):
        construct_stage(
            stage_path="$.pipeline.stages[0]",
            factory=StageFactorySpec(
                target_path="tests.unit.loom.pipeline.test_stage_factory:IncompleteStage",
            ),
        )


def test_construct_stage_imports_fresh_project_target_and_preserves_constructor_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name = "fresh_failing_project_target"
    marker_path = tmp_path / "target-events.txt"
    (tmp_path / f"{module_name}.py").write_text(
        "from pathlib import Path\n"
        f"MARKER = Path({str(marker_path)!r})\n"
        "MARKER.write_text('imported\\n', encoding='utf-8')\n"
        "class ProjectConstructorError(Exception):\n"
        "    pass\n"
        "class FailingProjectStage:\n"
        "    def __init__(self) -> None:\n"
        "        MARKER.write_text('imported\\nconstructed\\n', encoding='utf-8')\n"
        "        raise ProjectConstructorError('fresh constructor sentinel')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    assert module_name not in sys.modules
    with pytest.raises(StageContractError, match="could not construct stage") as error:
        construct_stage(
            stage_path="$.pipeline.stages[0]",
            factory=StageFactorySpec(
                target_path=f"{module_name}:FailingProjectStage",
            ),
        )

    assert marker_path.read_text(encoding="utf-8") == "imported\nconstructed\n"
    cause = error.value.__cause__
    assert cause is not None
    assert type(cause).__name__ == "ProjectConstructorError"
    assert str(cause) == "fresh constructor sentinel"


def cast_init_value(stage: Stage) -> int:
    return getattr(stage, "value", -1)
