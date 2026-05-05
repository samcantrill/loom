"""Unit tests for interpolation wrapping."""

from __future__ import annotations

import pytest
from omegaconf import OmegaConf

from loom.config.errors import ConfigInterpolationError, ConfigUnsupportedResolverError
from loom.config.interpolation import (
    ResolverExpressionRecord,
    resolve_interpolation,
    scan_resolver_expressions,
)


def test_resolve_simple_config_node_interpolation() -> None:
    resolved = resolve_interpolation({"paths": {"root": "root", "child": "${paths.root}/child"}})
    paths = resolved["paths"]
    assert isinstance(paths, dict)
    assert paths["child"] == "root/child"


def test_reject_resolver_style_interpolation() -> None:
    with pytest.raises(ConfigUnsupportedResolverError):
        resolve_interpolation({"value": "${env:HOME}"})


def test_reject_unresolved_interpolation() -> None:
    with pytest.raises(ConfigInterpolationError):
        resolve_interpolation({"value": "${missing.path}"})


def test_scan_resolver_expressions_preserves_config_data() -> None:
    source = {
        "plain": "value",
        "resolved": "${root.path}",
        "resolver": "${oc.env:HOME}/x",
        "list": [
            "${paths.root}/one",
            {"nested": "${env:HOME}"},
        ],
    }
    plain, records = scan_resolver_expressions(source, path="$")

    assert plain["plain"] == "value"
    assert plain["resolved"] == "${root.path}"
    assert plain["resolver"] == "${oc.env:HOME}/x"
    assert plain["list"][1]["nested"] == "${env:HOME}"

    assert [record.config_path for record in records] == [
        "$.['resolver']",
        "$.['list'][1]['nested']",
    ]
    assert records == (
        ResolverExpressionRecord(
            config_path="$.['resolver']",
            token="${oc.env:HOME}",
            resolver="oc.env",
            expression="oc.env:HOME",
        ),
        ResolverExpressionRecord(
            config_path="$.['list'][1]['nested']",
            token="${env:HOME}",
            resolver="env",
            expression="env:HOME",
        ),
    )


def test_scan_resolver_expressions_no_execution_sentinel() -> None:
    called: list[str] = []

    def sentinel(value: str) -> str:
        called.append(value)
        return f"value::{value}"

    OmegaConf.register_new_resolver("sentinel", sentinel, replace=True)
    try:
        plain, records = scan_resolver_expressions({"value": "${sentinel:payload}"}, path="$")
        assert plain["value"] == "${sentinel:payload}"
        assert records[0].resolver == "sentinel"
        assert called == []
    finally:
        OmegaConf.clear_resolver("sentinel")


def test_resolve_allows_oc_env_during_runtime_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHASE8_TEST_ENV", "injected")
    resolved = resolve_interpolation(
        {"value": "${oc.env:PHASE8_TEST_ENV}"},
        source_path="/tmp/base.yaml",
        path="$",
    )
    assert resolved["value"] == "injected"


def test_resolve_rejects_non_allowlisted_builtin_resolver() -> None:
    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        resolve_interpolation(
            {"value": "${oc.create:dict}"},
            source_path="/tmp/base.yaml",
            path="$",
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_resolver"
    assert context.actual == "oc.create"


@pytest.mark.parametrize(
    "resolver_token",
    ["oc.decode:${x}", "oc.select:${x}", "oc.dict.keys:${x}", "oc.dict.values:${x}"],
)
def test_reject_other_non_allowlisted_omega_conf_builtin_resolvers(resolver_token: str) -> None:
    with pytest.raises(ConfigUnsupportedResolverError) as exc:
        resolve_interpolation(
            {"value": f"${{{resolver_token}}}"},
            source_path="/tmp/base.yaml",
            path="$",
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_resolver"
    assert context.actual == resolver_token.split(":", 1)[0]
