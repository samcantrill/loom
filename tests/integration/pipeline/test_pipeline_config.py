"""Integration test that pipeline specs consume composed config."""

from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

import loom.config.api as config_api
from loom.config import RecipeCatalog, compose_config, compose_config_with_catalog, register_recipe
from loom.config.errors import UnknownRecipeError
from loom.pipeline import PipelineSpec, parse_pipeline_config
from loom.pipeline.graph import build_stage_graph, topological_sort


pytestmark = pytest.mark.optional_dependency


def pipeline_recipe(*, title: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    del title
    return {
        "name": "expanded",
        "stages": [
            {
                "name": "build",
                "factory": {"_target_": "tests.support.config_samples:concat"},
                "outputs": {
                    "text": {"artifact_type": "text"},
                },
            },
            {
                "name": "report",
                "factory": {"_target_": "tests.support.config_samples:concat"},
                "depends_on": ["build"],
                "inputs": {"text": "build.text"},
                "outputs": {"report": {"artifact_type": "text"}},
            },
        ],
    }


def test_composed_config_pipeline_is_parseable(tmp_path: Path) -> None:
    base = tmp_path / "config.yaml"
    base.write_text(
        "name: root-pipeline\n"
        "pipeline:\n"
        "  _recipe_: phase6_pipeline\n"
        "  title: test-pipeline\n",
        encoding="utf-8",
    )
    catalog = RecipeCatalog()
    catalog.register("phase6_pipeline", pipeline_recipe)

    composed = compose_config(base, recipe_catalog=catalog)
    pipeline_config = cast(dict[str, Any], composed.resolved["pipeline"])
    spec = PipelineSpec.from_config(pipeline_config)
    assert len(spec.stages) == 2

    graph = build_stage_graph(spec)
    assert topological_sort(graph) == ["build", "report"]
    assert parse_pipeline_config(pipeline_config) == spec


def test_pipeline_config_uses_fresh_catalog_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "pipeline.yaml"
    base.write_text(
        "name: root-pipeline\n"
        "pipeline:\n"
        "  _recipe_: phase6_pipeline\n"
        "  title: test-pipeline\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config_api, "__default_recipe_catalog", RecipeCatalog())
    register_recipe("phase6_pipeline", pipeline_recipe)

    with pytest.raises(UnknownRecipeError):
        compose_config_with_catalog(base, recipe_catalog=RecipeCatalog())

    explicit_catalog = RecipeCatalog()
    explicit_catalog.register("phase6_pipeline", pipeline_recipe)
    composed = compose_config_with_catalog(base, recipe_catalog=explicit_catalog)
    pipeline_config = cast(dict[str, Any], composed.resolved["pipeline"])
    spec = PipelineSpec.from_config(pipeline_config)
    assert len(spec.stages) == 2
