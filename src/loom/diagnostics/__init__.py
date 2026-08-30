"""Public diagnostics APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    ArtifactBackendPreflightTarget,
    CleanupPreflightTarget,
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
    from .run_inspection import (
        RunInspectionAxis,
        RunInspectionAxisName,
        RunInspectionFailure,
        RunInspectionFailureCode,
        RunInspectionLocation,
        RunInspectionProjection,
        RunInspectionResponse,
        RunInspectionResult,
        RunInspectionStage,
        RunInspectionTruncation,
        RunLocationReachability,
    )


def run_preflight(request: PreflightRequest) -> PreflightResult:
    from .preflight import run_preflight as _run_preflight

    return _run_preflight(request)


def inspect_run(run_uri: str, **kwargs: object) -> "RunInspectionResponse":
    """Lazily inspect one run through the schema-v1 projection."""
    from .run_inspection import inspect_run as _inspect_run

    return _inspect_run(run_uri, **kwargs)  # type: ignore[no-any-return]


def decode_run_inspection_response(data: object) -> "RunInspectionResponse":
    """Decode a schema-v1 inspection result or closed failure."""
    from .run_inspection import decode_run_inspection_response as _decode

    return _decode(data)


def projection_callable(**kwargs: object) -> "object":
    """Return the injected plain-data inspection callable."""
    from .run_inspection import projection_callable as _projection_callable

    return _projection_callable(**kwargs)


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
    if name in {
        "RunInspectionAxis", "RunInspectionAxisName", "RunInspectionFailure",
        "RunInspectionFailureCode", "RunInspectionLocation", "RunInspectionProjection",
        "RunInspectionResponse", "RunInspectionResult", "RunInspectionStage",
        "RunInspectionTruncation", "RunLocationReachability",
    }:
        from . import run_inspection
        return getattr(run_inspection, name)
    raise AttributeError(f"module 'loom.diagnostics' has no attribute {name!r}")


__all__ = [
    "PreflightStatus",
    "PreflightCheckStatus",
    "PreflightSeverity",
    "PreflightGroup",
    "ArtifactBackendPreflightTarget",
    "CleanupPreflightTarget",
    "PreflightCheckResult",
    "PreflightResult",
    "PreflightRequest",
    "PreflightError",
    "BackendCapabilitiesResult",
    "BackendDiagnosticsError",
    "BackendInspectionResult",
    "inspect_backend",
    "inspect_backend_capabilities",
    "parse_projection_revision",
    "run_preflight",
    "RunInspectionAxis", "RunInspectionAxisName", "RunInspectionFailure",
    "RunInspectionFailureCode", "RunInspectionLocation", "RunInspectionProjection",
    "RunInspectionResponse", "RunInspectionResult", "RunInspectionStage",
    "RunInspectionTruncation", "RunLocationReachability", "inspect_run",
    "decode_run_inspection_response", "projection_callable",
]
