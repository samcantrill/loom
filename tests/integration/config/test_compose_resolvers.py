"""Integration coverage for runtime resolver allow-listing."""

from pathlib import Path

import pytest
from omegaconf import OmegaConf
from omegaconf.resolvers import oc as omegaconf_oc

from weave import compose_config
from weave.errors import ConfigIncludeResolutionError, ConfigUnsupportedResolverError
from weave.redaction import REDACTION_MARKER


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


def test_public_compose_uses_loom_owned_oc_env_when_global_resolver_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "paths:\n"
        "  root: ${oc.env:PHASE8_COMPOSE_ROOT}\n"
        "pipeline:\n"
        "  data: ${paths.root}/value\n",
        encoding="utf-8",
    )
    called: list[str] = []

    def replaced_oc_env(value: str) -> str:
        called.append(value)
        return "/tmp/global-replacement"

    monkeypatch.setenv("PHASE8_COMPOSE_ROOT", "/tmp/loom-owned-root")
    OmegaConf.register_new_resolver("oc.env", replaced_oc_env, replace=True)
    try:
        composed = compose_config(base)
    finally:
        OmegaConf.register_new_resolver("oc.env", omegaconf_oc.env, replace=True)

    pipeline = composed.resolved["pipeline"]
    assert isinstance(pipeline, dict)
    assert pipeline["data"] == "/tmp/loom-owned-root/value"
    assert called == []


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


def test_public_compose_attributes_overlay_authored_resolver_error(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("name: base\npipeline:\n  value: base\n", encoding="utf-8")
    overlay.write_text("pipeline:\n  value: ${custom:HOME}\n", encoding="utf-8")

    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        compose_config(base, overlays=(overlay,))

    context = exc.value.context
    assert context is not None
    assert context.source_kind == "overlay"
    assert context.source_path == str(overlay)
    assert context.source_order == 1
    assert context.config_path == "$.pipeline.value"
    assert context.details is not None
    assert context.details["authorship_missing"] is False


def test_public_compose_attributes_override_authored_resolver_error_without_raw_secret(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("name: base\npipeline:\n  token: base\n", encoding="utf-8")

    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        compose_config(base, overrides=("pipeline.token=${custom:SECRET_VALUE}",))

    context = exc.value.context
    assert context is not None
    assert context.source_kind == "ordinary_override"
    assert context.source_path == "<override>"
    assert context.config_path == "$.pipeline.token"
    assert context.details is not None
    serialized = str(context.to_dict())
    assert context.details["authored_expression"] == REDACTION_MARKER
    assert "SECRET_VALUE" not in serialized
    assert "pipeline.token=${custom:SECRET_VALUE}" not in serialized


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
