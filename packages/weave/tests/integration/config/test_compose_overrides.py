"""Integration checks for user composition overrides."""

from pathlib import Path
from typing import cast

import pytest
from weave import compose_config
from weave.errors import ConfigIncludeExpansionError, ConfigIncludeResolutionError, OverrideApplyError
from weave.plain import PlainData


def _mapping(value: object) -> dict[str, PlainData]:
    assert isinstance(value, dict)
    return cast(dict[str, PlainData], value)


def test_public_compose_replaces_existing_include_with_local_replay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()

    (include_dir / "model-old.yaml").write_text(
        "shared: old\n"
        "marker: old-marker\n",
        encoding="utf-8",
    )
    (include_dir / "model-new.yaml").write_text(
        "shared: new\n"
        "fresh: added\n",
        encoding="utf-8",
    )

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/model-old.yaml\n"
        "    shared: from-base\n"
        "    added: value\n",
        encoding="utf-8",
    )

    composed = compose_config(
        base,
        overrides=("pipeline.model._include_=./include/model-new.yaml",),
    )

    model = _mapping(composed.resolved["pipeline"])
    model = _mapping(model["model"])
    assert model["shared"] == "from-base"
    assert model["added"] == "value"
    assert model["fresh"] == "added"
    assert "marker" not in model


def test_public_compose_rejects_add_operation_for_existing_include_site(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()

    (include_dir / "model-old.yaml").write_text("shared: old\n", encoding="utf-8")
    (include_dir / "model-new.yaml").write_text("shared: new\n", encoding="utf-8")

    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/model-old.yaml\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base, overrides=("+pipeline.model._include_=./include/model-new.yaml",))

    context = exc.value.context
    assert context is not None
    assert context.code == "existing_include_site"
    assert context.details is not None
    assert context.details["reason"] == "add_existing_include_site"
    assert context.details["override_raw"] == "+pipeline.model._include_=./include/model-new.yaml"


def test_public_compose_wraps_non_mapping_replacement_target_with_user_context(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()

    (include_dir / "model-old.yaml").write_text("shared: old\n", encoding="utf-8")
    (include_dir / "model-list.yaml").write_text("- not\n- mapping\n", encoding="utf-8")

    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/model-old.yaml\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base, overrides=("pipeline.model._include_=./include/model-list.yaml",))

    context = exc.value.context
    assert context is not None
    assert context.code == "included_root_not_mapping"
    assert context.config_path == "$.pipeline.model._include_"
    assert context.details is not None
    assert context.details["reason"] == "replacement_root_not_mapping"
    assert context.details["override_raw"] == "pipeline.model._include_=./include/model-list.yaml"
    assert context.details["actual"] == "list"


def test_public_compose_replaces_nested_existing_include_with_source_local_bare_target(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    nested_dir = include_dir / "component"
    nested_dir.mkdir(parents=True)
    (tmp_path / "replacement.yaml").write_text("value: wrong\n", encoding="utf-8")

    (include_dir / "root.yaml").write_text(
        "component:\n"
        "  _include_: nested\n",
        encoding="utf-8",
    )
    (nested_dir / "nested.yaml").write_text("value: nested-old\n", encoding="utf-8")
    (nested_dir / "replacement.yaml").write_text("value: nested-new\n", encoding="utf-8")

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/root.yaml\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overrides=("pipeline.model.component._include_=replacement",))
    model = _mapping(_mapping(composed.resolved["pipeline"])["model"])
    component = _mapping(model["component"])

    assert component["value"] == "nested-new"


def test_public_compose_adds_brand_new_include_from_explicit_relative_target(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included_dir = tmp_path / "components"
    included_dir.mkdir()
    (included_dir / "dataset.yaml").write_text("kind: tabular\nrows: 100\n", encoding="utf-8")

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  existing: true\n",
        encoding="utf-8",
    )

    composed = compose_config(
        base,
        overrides=("+pipeline.dataset._include_=./components/dataset.yaml",),
    )
    dataset = _mapping(_mapping(composed.resolved["pipeline"])["dataset"])

    assert dataset["kind"] == "tabular"
    assert dataset["rows"] == 100


def test_public_compose_rejects_brand_new_bare_include_target(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("pipeline: {}\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base, overrides=("+pipeline.dataset._include_=dataset",))

    context = exc.value.context
    assert context is not None
    assert context.code == "new_include_requires_explicit_target"
    assert context.details is not None
    assert context.details["reason"] == "explicit_target_required"


def test_public_compose_rejects_brand_new_include_over_existing_dataset(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included_dir = tmp_path / "components"
    included_dir.mkdir()
    (included_dir / "dataset.yaml").write_text("kind: tabular\n", encoding="utf-8")

    base.write_text(
        "pipeline:\n"
        "  dataset:\n"
        "    existing: from-base\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base, overrides=("+pipeline.dataset._include_=./components/dataset.yaml",))

    context = exc.value.context
    assert context is not None
    assert context.code == "existing_include_container"


def test_public_compose_applies_ordinary_overrides_after_include_recomposition(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included_dir = tmp_path / "includes"
    included_dir.mkdir()

    (included_dir / "model-base.yaml").write_text(
        "shared: from-include\n",
        encoding="utf-8",
    )
    (included_dir / "model-repl.yaml").write_text(
        "shared: replaced\n"
        "added: from-repl\n",
        encoding="utf-8",
    )

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./includes/model-base.yaml\n"
        "    shared: from-base\n"
        "    kept: keep-value\n",
        encoding="utf-8",
    )

    composed = compose_config(
        base,
        overrides=(
            "pipeline.model._include_=./includes/model-repl.yaml",
            "pipeline.model.shared=first-update",
            "pipeline.model.shared=second-update",
            "+pipeline.flags=true",
        ),
    )

    model = _mapping(_mapping(composed.resolved["pipeline"])["model"])
    assert model["shared"] == "second-update"
    assert model["kept"] == "keep-value"
    assert model["added"] == "from-repl"
    pipeline = _mapping(composed.resolved["pipeline"])
    assert pipeline["flags"] is True


def test_public_compose_override_paths_do_not_address_literal_dot_keys(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text('"model.name": literal\n', encoding="utf-8")

    with pytest.raises(OverrideApplyError):
        compose_config(base, overrides=("model.name=changed",))


def test_public_compose_override_backslash_is_not_literal_dot_escape(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text('"model.name": literal\n', encoding="utf-8")

    with pytest.raises(OverrideApplyError):
        compose_config(base, overrides=(r"model\.name=changed",))


def test_public_compose_add_override_with_dotted_path_creates_nested_segments_not_literal_key(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text('"model.name": literal\n', encoding="utf-8")

    composed = compose_config(base, overrides=("+model.name=segmented",))

    assert composed.resolved == {
        "model.name": "literal",
        "model": {"name": "segmented"},
    }


def test_public_compose_rejects_existing_include_override_with_resolver_expression(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()

    (include_dir / "model-old.yaml").write_text("shared: old\n", encoding="utf-8")

    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/model-old.yaml\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        compose_config(base, overrides=("pipeline.model._include_=${oc.env:PHASE8_MODEL}",))

    context = exc.value.context
    assert context is not None
    assert context.code == "resolver_dependent"
    assert context.details is not None
    assert context.details["reason"] == "interpolation_token"


def test_public_compose_rejects_brand_new_include_override_with_resolver_expression(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("pipeline: {}\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        compose_config(base, overrides=("+pipeline.dataset._include_=${oc.env:PHASE8_DATASET}",))

    context = exc.value.context
    assert context is not None
    assert context.code == "resolver_dependent"
    assert context.details is not None
    assert context.details["reason"] == "interpolation_token"
