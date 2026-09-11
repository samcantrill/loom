"""Required-check semantics at the coordinator publication boundary."""

import pytest

from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightResult,
    PreflightSeverity,
)
from loom.preparation import preparation_checks_allow_publication


@pytest.mark.parametrize(
    "status,applicability,allowed",
    (
        (PreflightCheckStatus.SKIP, "required", False),
        (PreflightCheckStatus.SKIP, "not_applicable", True),
        (PreflightCheckStatus.WARN, "required", True),
        (PreflightCheckStatus.FAIL, "required", False),
    ),
)
def test_publication_respects_required_checks_without_hiding_other_findings(
    status: PreflightCheckStatus,
    applicability: str,
    allowed: bool,
) -> None:
    result = PreflightResult(
        (
            PreflightCheckResult(
                "config.compose",
                PreflightGroup.CONFIG,
                PreflightCheckStatus.PASS,
                PreflightSeverity.INFO,
                "composition available",
                {},
            ),
            PreflightCheckResult(
                "runtime.options",
                PreflightGroup.RUNTIME,
                status,
                PreflightSeverity.INFO,
                "native runtime finding",
                {"applicability": applicability},
            ),
        ),
        (PreflightGroup.CONFIG, PreflightGroup.RUNTIME),
    )
    received = PreflightResult.from_dict(result.to_dict())
    assert preparation_checks_allow_publication(received) is allowed
    assert received == result
