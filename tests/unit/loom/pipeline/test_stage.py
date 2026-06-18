"""Unit tests for Stage protocol contract."""

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import Stage, StageContext


class SyntheticStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        assert context
        assert inputs is not None
        return {}


def test_structural_stage_protocol() -> None:
    assert isinstance(SyntheticStage(), Stage)

