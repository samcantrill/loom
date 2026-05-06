"""Unit tests for CLI formatting helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom.cli.formatting import (
    CLI_RESULT_SCHEMA_VERSION,
    format_json_envelope,
    format_plan_text,
    format_run_text,
    format_validation_text,
)
from loom.cli.results import CliWarning, PlanCliResult, RunCliResult, ValidationCliResult


pytestmark = pytest.mark.unit


def test_format_json_envelope_uses_top_level_warnings() -> None:
    rendered = format_json_envelope(
        schema_version=CLI_RESULT_SCHEMA_VERSION,
        ok=True,
        warnings=[CliWarning(code="config.notice", message="heads up", details={"path": Path("x")})],
        payload_name="result",
        payload={"config_path": Path("pipeline.yaml"), "items": ("a", "b")},
    )

    assert rendered.endswith("\n")
    payload = json.loads(rendered)
    assert payload == {
        "schema_version": CLI_RESULT_SCHEMA_VERSION,
        "ok": True,
        "warnings": [
            {"code": "config.notice", "message": "heads up", "details": {"path": "x"}},
        ],
        "result": {"config_path": "pipeline.yaml", "items": ["a", "b"]},
    }


def test_format_json_envelope_rejects_unknown_payload_name() -> None:
    with pytest.raises(ValueError, match="payload name"):
        format_json_envelope(
            schema_version=CLI_RESULT_SCHEMA_VERSION,
            ok=True,
            warnings=[],
            payload_name="data",
            payload={},
        )


def test_text_formatters_are_concise() -> None:
    assert (
        format_validation_text(ValidationCliResult(config_path=Path("pipeline.yaml"), stage_count=2))
        == "OK validate pipeline.yaml: 2 stages"
    )
    assert (
        format_plan_text(
            PlanCliResult(
                config_path=Path("pipeline.yaml"),
                run_uri="file://./runs/example",
                stage_actions=({"stage": "a"},),
            )
        )
        == "OK plan pipeline.yaml: 1 stage action, run_uri=file://./runs/example"
    )
    assert format_run_text(RunCliResult(run_uri="file://./runs/example", status="succeeded")) == (
        "OK run file://./runs/example: succeeded"
    )
