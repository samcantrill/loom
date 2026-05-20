"""Unit tests for recipe manifest records."""

from weave.recipes import RecipeManifestRecord
from tests.support.config_samples import function_recipe
from weave.digests import hash_mapping


def test_manifest_record_shape_and_hash() -> None:
    manifest = RecipeManifestRecord.for_expansion(
        path="pipeline",
        name="fn",
        recipe=function_recipe,
        arguments={"value": "x"},
        expanded={"value": "x", "nested": {"keep": "yes"}},
    )

    expected_hash = hash_mapping({"value": "x", "nested": {"keep": "yes"}})
    payload = manifest.to_dict()

    assert payload["path"] == "pipeline"
    assert payload["name"] == "fn"
    assert payload["target"] == "tests.support.config_samples:function_recipe"
    assert payload["arguments"] == {"value": "x"}
    assert payload["expanded_hash"] == expected_hash
    assert payload["expanded_path"] == "pipeline"
    assert isinstance(payload["loom_version"], str)
    assert len(payload["loom_version"]) > 0


def test_manifest_target_stable_for_callables() -> None:
    manifest = RecipeManifestRecord.for_expansion(
        path="pipeline",
        name="fn",
        recipe=function_recipe,
        arguments={},
        expanded={},
    )

    assert manifest.target == "tests.support.config_samples:function_recipe"
