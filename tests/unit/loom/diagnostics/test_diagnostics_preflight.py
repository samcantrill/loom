"""Unit tests for the local preflight runner."""

from __future__ import annotations

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
