"""Contract tests for ``loom preflight`` CLI output."""

from __future__ import annotations

import json

import pytest

from loom.cli.formatting import format_json_envelope
from loom.cli.preflight import PREFLIGHT_RESULT_SCHEMA_VERSION
from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightResult,
    PreflightSeverity,
)


pytestmark = pytest.mark.contract


def test_preflight_json_result_envelope_contract() -> None:
    result = PreflightResult(
        checks=(
            PreflightCheckResult(
                check_id="config.load",
                group=PreflightGroup.CONFIG,
                status=PreflightCheckStatus.FAIL,
                severity=PreflightSeverity.ERROR,
                message="config composition failed",
                details={"error_type": "ConfigError", "error": "bad config"},
            ),
        ),
        groups=(PreflightGroup.CONFIG,),
    )

    payload = json.loads(
        format_json_envelope(
            schema_version=PREFLIGHT_RESULT_SCHEMA_VERSION,
            ok=False,
            warnings=[],
            payload_name="result",
            payload=result.to_dict(),
        )
    )

    assert payload == {
        "schema_version": "loom.cli.preflight.v3",
        "ok": False,
        "warnings": [],
        "result": {
            "status": "FAIL",
            "groups": ["config"],
            "checks": [
                {
                    "check_id": "config.load",
                    "group": "config",
                    "status": "FAIL",
                    "severity": "ERROR",
                    "message": "config composition failed",
                    "details": {
                        "error_type": "ConfigError",
                        "error": "bad config",
                    },
                }
            ],
        },
    }
