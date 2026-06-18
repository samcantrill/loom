"""Contract tests for Stage protocol implementations."""

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import Stage


class DummyStage:
    def run(self, context, inputs: Mapping[str, ArtifactRef]) -> Mapping[str, ArtifactRef]:
        return {}


class IncompleteStage:
    pass


def test_downstream_stage_is_structural_protocol_compatible() -> None:
    assert isinstance(DummyStage(), Stage)


def test_protocol_requires_run_method() -> None:
    assert not isinstance(IncompleteStage(), Stage)
