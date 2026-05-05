"""Integration coverage for runtime resolver allow-listing."""

from pathlib import Path

import pytest

from loom.config import compose_config
from loom.config.errors import ConfigIncludeResolutionError, ConfigUnsupportedResolverError


def test_public_compose_resolves_oc_env_in_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE8_COMPOSE_ROOT}\n"
        "pipeline:\n"
        "  data: ${paths.root}/value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PHASE8_COMPOSE_ROOT", "/tmp/phase8-root")

    composed = compose_config(base)
    pipeline = composed.resolved["pipeline"]
    assert isinstance(pipeline, dict)
    assert pipeline["data"] == "/tmp/phase8-root/value"


def test_public_compose_rejects_non_allowlisted_builtin_resolver(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline:\n  value: ${oc.create:dict}\n", encoding="utf-8")

    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_resolver"
    assert context.actual == "oc.create"


def test_public_compose_rejects_user_resolver_expression(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline:\n  value: ${custom:HOME}\n", encoding="utf-8")

    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_resolver"
    assert context.actual == "custom"


def test_public_compose_rejects_include_target_resolver_expression(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ${oc.env:PHASE8_INCLUDE}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "resolver_dependent"
    assert context.details is not None
    assert context.details["reason"] == "interpolation_token"
