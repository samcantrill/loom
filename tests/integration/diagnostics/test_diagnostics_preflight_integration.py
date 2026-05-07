"""Integration tests for local diagnostics preflight checks."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("omegaconf")
pytest.importorskip("pydantic")

from loom.diagnostics import PreflightCheckStatus, PreflightRequest, PreflightStatus, run_preflight
from loom.pipeline.stores import path_to_run_uri


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_full_local_preflight_passes_and_writes_no_run_documents(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)
    run_dir = tmp_path / "runs" / "demo-run"

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            run_uri=path_to_run_uri(run_dir),
        )
    )

    assert result.status is PreflightStatus.PASS
    assert [check.check_id for check in result.checks] == [
        "config.load",
        "pipeline.graph",
        "selectors.validate",
        "runtime.options",
        "runtime.profile",
        "runtime.stage_options",
        "run_uri.resolve",
        "artifact_store.available",
        "codec_registry.available",
        "executor.local",
        "executor.resolve",
        "executor.capabilities",
        "resources.capabilities",
        "filesystem.input_exists",
    ]
    assert all(check.status is PreflightCheckStatus.PASS for check in result.checks)
    assert not run_dir.exists()


def test_selected_groups_run_only_selected_checks(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    result = run_preflight(
        PreflightRequest(config_path=config_path, groups=("pipeline", "selectors"))
    )

    assert result.status is PreflightStatus.PASS
    assert [group.value for group in result.groups] == ["pipeline", "selectors"]
    assert [check.check_id for check in result.checks] == [
        "pipeline.graph",
        "selectors.validate",
    ]


def test_omitted_run_uri_skips_only_run_path_dependent_checks(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    result = run_preflight(PreflightRequest(config_path=config_path))

    by_id = {check.check_id: check for check in result.checks}
    assert result.status is PreflightStatus.PASS
    assert by_id["run_uri.resolve"].status is PreflightCheckStatus.SKIP
    assert by_id["artifact_store.available"].status is PreflightCheckStatus.SKIP
    assert by_id["filesystem.input_exists"].status is PreflightCheckStatus.PASS
    assert by_id["config.load"].status is PreflightCheckStatus.PASS


def test_selector_validation_reports_unknown_stage(tmp_path: Path) -> None:
    config_path = _write_valid_config(tmp_path)

    result = run_preflight(
        PreflightRequest(
            config_path=config_path,
            groups=("selectors",),
            selectors={"only_stages": ["missing"]},
        )
    )

    assert result.status is PreflightStatus.FAIL
    check = result.checks[0]
    assert check.check_id == "selectors.validate"
    assert check.details["error_type"] == "SelectorValidationError"


def _write_valid_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        """
pipeline:
  name: demo
  stages:
    - name: build
      factory:
        _target_: tests.support.pipeline_execution_stages.JsonProducerStage
      config:
        value: 1
      outputs:
        data:
          artifact_type: json
          codec_key: json.v1
    - name: report
      factory:
        _target_: tests.support.pipeline_execution_stages.TextConsumerStage
      inputs:
        data: build.data
      outputs:
        text:
          artifact_type: text
          codec_key: text.v1
""".lstrip(),
        encoding="utf-8",
    )
    return config_path
