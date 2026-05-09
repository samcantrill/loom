"""Public diagnostics APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from .backend import (
        BackendCapabilitiesResult,
        BackendDiagnosticsError,
        BackendInspectionResult,
        inspect_backend,
        inspect_backend_capabilities,
        parse_projection_revision,
    )


def run_preflight(request: PreflightRequest) -> PreflightResult:
    from .preflight import run_preflight as _run_preflight

    return _run_preflight(request)


def __getattr__(name: str) -> object:
    if name in {
        "BackendCapabilitiesResult",
        "BackendDiagnosticsError",
        "BackendInspectionResult",
        "inspect_backend",
        "inspect_backend_capabilities",
        "parse_projection_revision",
    }:
        from . import backend

        return getattr(backend, name)
    raise AttributeError(f"module 'loom.diagnostics' has no attribute {name!r}")


__all__ = [
    "BackendCapabilitiesResult",
    "BackendDiagnosticsError",
    "BackendInspectionResult",
    "PreflightStatus",
    "PreflightCheckStatus",
    "PreflightSeverity",
    "PreflightGroup",
    "PreflightCheckResult",
    "PreflightResult",
    "PreflightRequest",
    "PreflightError",
    "inspect_backend",
    "inspect_backend_capabilities",
    "parse_projection_revision",
    "run_preflight",
]
