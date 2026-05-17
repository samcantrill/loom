"""Package-level API tests for runtime reliability contracts."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_runtime_namespace_exports_reliability_contract_surface() -> None:
    from loom.pipeline.runtime import (
        FailureClassification,
        ReliabilityPolicy,
        ReliabilityStatusDetail,
        RetryDecisionRecord,
        RetryPolicy,
        StageAttemptTransaction,
        StageAttemptTransactionState,
        TimeoutAdapter,
        TimeoutOutcome,
        TimeoutOutcomeRecord,
        TimeoutPolicy,
        TimeoutSupportLevel,
    )

    assert ReliabilityPolicy
    assert ReliabilityStatusDetail
    assert FailureClassification
    assert RetryPolicy
    assert RetryDecisionRecord
    assert StageAttemptTransaction
    assert StageAttemptTransactionState
    assert TimeoutOutcomeRecord
    assert TimeoutOutcome
    assert TimeoutPolicy
    assert TimeoutSupportLevel
    assert TimeoutAdapter


def test_pipeline_reliability_imports_are_import_light() -> None:
    script = dedent(
        """
        import sys

        from loom.pipeline import reliability

        for forbidden in (
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "loom.pipeline.stores",
            "loom.cli",
            "loom.config",
            "loom.diagnostics",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} was imported through loom.pipeline.reliability")

        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
