"""Public diagnostics APIs."""

from __future__ import annotations

from .models import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightError,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
    PreflightStatus,
)


def run_preflight(request: PreflightRequest) -> PreflightResult:
    from .preflight import run_preflight as _run_preflight

    return _run_preflight(request)


__all__ = [
    "PreflightStatus",
    "PreflightCheckStatus",
    "PreflightSeverity",
    "PreflightGroup",
    "PreflightCheckResult",
    "PreflightResult",
    "PreflightRequest",
    "PreflightError",
    "run_preflight",
]
