"""Public compose_config include-cycle diagnostics."""

from pathlib import Path

import pytest

from weave import compose_config
from weave.errors import ConfigIncludeExpansionError


def test_public_compose_reports_include_cycle_with_structured_context(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    include_a = include_dir / "a.yaml"
    include_b = include_dir / "b.yaml"

    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/a.yaml\n",
        encoding="utf-8",
    )
    include_a.write_text("bridge:\n  _include_: ./b.yaml\n", encoding="utf-8")
    include_b.write_text("bridge:\n  _include_: ./a.yaml\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "include_cycle"
    assert context.config_path == "$.pipeline.model.bridge.bridge._include_"
    assert context.source_path == str(include_b.resolve())
    assert context.source_kind == "overlay"
    assert context.source_order == 0
    assert context.directive == "_include_"

    serialized_context = context.to_dict()
    assert serialized_context["code"] == "include_cycle"
    assert serialized_context["config_path"] == "$.pipeline.model.bridge.bridge._include_"
    assert serialized_context["source_path"] == str(include_b.resolve())
    assert serialized_context["source_kind"] == "overlay"
    assert serialized_context["source_order"] == 0

    details = context.details
    assert details is not None
    assert details["reason"] == "include_cycle"
    assert details["attempted_target"] == str(include_a.resolve())
    assert details["attempted_include_site_path"] == [
        "pipeline",
        "model",
        "bridge",
        "bridge",
        "_include_",
    ]
    assert details["authored_target"] == "./a.yaml"

    include_stack = details["include_stack"]
    assert isinstance(include_stack, list)
    assert len(include_stack) == 2
    assert all(isinstance(frame, dict) for frame in include_stack)
    assert include_stack[0] == {
        "include_site_path": ["pipeline", "model", "_include_"],
        "authored_target": "./include/a.yaml",
        "source_path": str(base.resolve()),
        "source_kind": "base",
        "source_order": 0,
        "resolved_path": str(include_a.resolve()),
        "target_kind": "explicit_relative",
        "explicit_escape": True,
    }
    assert include_stack[1] == {
        "include_site_path": ["pipeline", "model", "bridge", "_include_"],
        "authored_target": "./b.yaml",
        "source_path": str(include_a.resolve()),
        "source_kind": "overlay",
        "source_order": 0,
        "resolved_path": str(include_b.resolve()),
        "target_kind": "explicit_relative",
        "explicit_escape": True,
    }
