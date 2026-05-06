"""Public compose_config error coverage for invalid YAML syntax."""

from pathlib import Path

import pytest

from loom.config import compose_config
from loom.config.errors import ConfigLoadError

pytestmark = pytest.mark.optional_dependency


def test_compose_config_wraps_invalid_overlay_yaml_with_structured_context(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("pipeline:\n  value: base\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  value: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base, overlays=(overlay,))

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_yaml"
    assert context.source_kind == "overlay"
    assert context.source_order == 1
    assert context.source_path == str(overlay.resolve())
    assert context.config_path is None
    assert context.remediation == "Fix YAML syntax and load again."


def test_public_compose_rejects_duplicate_keys_in_base_config(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("pipeline:\n  value: first\n  value: second\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.source_kind == "base"
    assert context.source_order == 0
    assert context.source_path == str(base.resolve())
    assert context.config_path == "$.pipeline.value"
    assert context.details == {"key": "value"}


def test_public_compose_rejects_duplicate_keys_in_overlay_config(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("pipeline:\n  value: base\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  stage: first\n  stage: second\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base, overlays=(overlay,))

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.source_kind == "overlay"
    assert context.source_order == 1
    assert context.source_path == str(overlay.resolve())
    assert context.config_path == "$.pipeline.stage"
    assert context.details == {"key": "stage"}


def test_public_compose_rejects_duplicate_keys_in_included_config(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"
    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n",
        encoding="utf-8",
    )
    included.write_text("stage: first\nstage: second\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.source_kind == "overlay"
    assert context.source_order == 0
    assert context.source_path == str(included.resolve())
    assert context.config_path == "$.stage"
    assert context.details == {"key": "stage"}
