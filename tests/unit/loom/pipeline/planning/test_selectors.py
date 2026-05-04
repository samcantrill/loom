"""Unit tests for planning selector normalization."""

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.graph import build_stage_graph
from loom.pipeline.planning import PlanSelectors, SelectorValidationError
from loom.pipeline.planning.selectors import normalize_selectors


def _spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "_target_": "project.Build",
                    "outputs": {"data": {"artifact_type": "json"}},
                },
                {
                    "name": "train",
                    "_target_": "project.Train",
                    "inputs": {"data": "build.data"},
                    "outputs": {"model": {"artifact_type": "bytes"}},
                },
                {
                    "name": "report",
                    "_target_": "project.Report",
                    "inputs": {"model": "train.model"},
                    "outputs": {"text": {"artifact_type": "text"}},
                },
            ],
        },
    )


def test_selector_duplicates_normalize_to_topological_order() -> None:
    spec = _spec()
    selection = normalize_selectors(
        PlanSelectors(force_stages=("report", "build", "build")),
        spec=spec,
        graph=build_stage_graph(spec),
    )
    assert selection.selectors.force_stages == ("build", "report")


def test_selector_conflicts_are_rejected_before_store_reads() -> None:
    spec = _spec()
    graph = build_stage_graph(spec)
    with pytest.raises(SelectorValidationError, match="mutually exclusive"):
        normalize_selectors(
            PlanSelectors(from_stage="train", only_stages=("report",)),
            spec=spec,
            graph=graph,
        )
    with pytest.raises(SelectorValidationError, match="overlap"):
        normalize_selectors(
            PlanSelectors(skip_stages=("train",), force_stages=("train",)),
            spec=spec,
            graph=graph,
        )
    with pytest.raises(SelectorValidationError, match="unknown"):
        normalize_selectors(
            PlanSelectors(only_stages=("missing",)), spec=spec, graph=graph
        )


def test_only_stage_uses_upstream_as_reuse_providers() -> None:
    spec = _spec()
    selection = normalize_selectors(
        PlanSelectors(only_stages=("report",)),
        spec=spec,
        graph=build_stage_graph(spec),
    )
    assert selection.eligible_stages == frozenset({"report"})
    assert selection.reusable_provider_stages == frozenset({"build", "train"})
