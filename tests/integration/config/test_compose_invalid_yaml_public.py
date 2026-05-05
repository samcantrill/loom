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
