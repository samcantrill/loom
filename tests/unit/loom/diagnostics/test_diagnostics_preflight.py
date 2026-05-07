"""Unit tests for the local preflight runner."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from loom.diagnostics import PreflightCheckStatus, PreflightRequest, PreflightStatus, run_preflight
from loom.diagnostics.models import PreflightError


pytestmark = pytest.mark.unit


def test_selected_codec_group_runs_only_codec_check() -> None:
    result = run_preflight(PreflightRequest(config_path="missing.yaml", groups=("codecs",)))

    assert result.status is PreflightStatus.PASS
    assert result.groups[0].value == "codecs"
    assert [check.check_id for check in result.checks] == ["codec_registry.available"]


def test_missing_run_uri_skips_run_path_dependent_groups() -> None:
    result = run_preflight(
        PreflightRequest(config_path="missing.yaml", groups=("run", "artifacts"))
    )

    assert result.status is PreflightStatus.SKIP
    assert [check.status for check in result.checks] == [
        PreflightCheckStatus.SKIP,
        PreflightCheckStatus.SKIP,
    ]
    assert [check.details["reason"] for check in result.checks] == [
        "missing_run_uri",
        "missing_run_uri",
    ]


def test_run_uri_group_uses_explicit_runtime_run_uri_without_config(
    tmp_path,
) -> None:
    from loom.pipeline.stores import path_to_run_uri

    run_uri = path_to_run_uri(tmp_path / "runs" / "demo")

    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={"run_uri": run_uri},
        )
    )

    assert result.status is PreflightStatus.PASS
    assert result.checks[0].check_id == "run_uri.resolve"
    assert result.checks[0].details["run_uri"] == run_uri


def test_run_uri_group_does_not_compose_config_for_non_uri_runtime_flags() -> None:
    result = run_preflight(
        PreflightRequest(
            config_path="missing.yaml",
            groups=("run",),
            runtime_options={"executor": "local"},
        )
    )

    assert result.status is PreflightStatus.SKIP
    assert result.checks[0].details["reason"] == "missing_run_uri"


def test_empty_selected_groups_are_request_errors() -> None:
    with pytest.raises(PreflightError, match="empty"):
        run_preflight(PreflightRequest(config_path="config.yaml", groups=()))


def test_unknown_selected_groups_are_request_errors() -> None:
    with pytest.raises(PreflightError, match="unknown preflight group"):
        run_preflight(PreflightRequest(config_path="config.yaml", groups=("nope",)))


def test_filesystem_check_reports_missing_inputs(tmp_path) -> None:
    result = run_preflight(
        PreflightRequest(
            config_path=tmp_path / "missing.yaml",
            groups=("filesystem",),
            overlays=(tmp_path / "overlay.yaml",),
        )
    )

    assert result.status is PreflightStatus.FAIL
    check = result.checks[0]
    assert check.check_id == "filesystem.input_exists"
    assert check.details["missing"] == [
        str(tmp_path / "missing.yaml"),
        str(tmp_path / "overlay.yaml"),
    ]


def test_runtime_executor_and_resource_checks_map_capability_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("runtime", "executor", "resources"),
            runtime_options={
                "executor": "local",
                "adapter_options": {"future": {"enabled": True}},
                "stage_options": {
                    "train": {
                        "resources": {
                            "entries": {"cpu": {"kind": "cpu", "amount": 2}}
                        }
                    }
                },
            },
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.WARN
    assert by_id["runtime.options"].status is PreflightCheckStatus.PASS
    assert by_id["runtime.stage_options"].status is PreflightCheckStatus.PASS
    assert by_id["executor.resolve"].status is PreflightCheckStatus.PASS
    assert by_id["executor.capabilities"].status is PreflightCheckStatus.WARN
    executor_diagnostics = cast(
        list[dict[str, Any]],
        by_id["executor.capabilities"].details["diagnostics"],
    )
    assert executor_diagnostics[0]["code"] == "adapter_namespace.unclaimed"
    assert by_id["resources.capabilities"].status is PreflightCheckStatus.WARN
    resource_diagnostics = cast(
        list[dict[str, Any]],
        by_id["resources.capabilities"].details["diagnostics"],
    )
    assert resource_diagnostics[0]["code"] == "resource.ignored"


def test_unknown_executor_fails_resolve_and_skips_capability_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime_preflight_dependencies(monkeypatch)

    result = run_preflight(
        PreflightRequest(
            config_path="config.yaml",
            groups=("executor", "resources"),
            runtime_options={"executor": "missing"},
        )
    )

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.FAIL
    assert by_id["executor.resolve"].status is PreflightCheckStatus.FAIL
    diagnostic = cast(dict[str, Any], by_id["executor.resolve"].details["diagnostic"])
    assert diagnostic["code"] == "executor.unknown"
    assert by_id["executor.capabilities"].status is PreflightCheckStatus.SKIP
    assert by_id["resources.capabilities"].status is PreflightCheckStatus.SKIP


@dataclass(frozen=True, slots=True)
class _FakeComposedConfig:
    resolved: dict[str, object]
    source_artifacts: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _FakeSpec:
    stage_names: tuple[str, ...] = ("train",)


@dataclass(frozen=True, slots=True)
class _FakePipelineValidation:
    spec: _FakeSpec = _FakeSpec()
    graph: object = object()
    stage_count: int = 1
    pipeline_name: str = "demo"


def _patch_runtime_preflight_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    import loom.pipeline

    config_package = ModuleType("loom.config")
    config_api = ModuleType("loom.config.api")
    setattr(
        config_api,
        "compose_config",
        lambda *_args, **_kwargs: _FakeComposedConfig(resolved={"pipeline": {}}),
    )
    setattr(config_package, "api", config_api)
    monkeypatch.setitem(sys.modules, "loom.config", config_package)
    monkeypatch.setitem(sys.modules, "loom.config.api", config_api)
    monkeypatch.setattr(
        loom.pipeline,
        "validate_pipeline_config",
        lambda _config: _FakePipelineValidation(),
    )
