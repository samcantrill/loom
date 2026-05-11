"""Operational supervisor routes for the authority service skeleton."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from loom.pipeline.stores import AUTHORITY_PROTOCOL_VERSION
from loom.serialization import PlainData

from ..dependencies import get_authority_services
from ..services import AuthorityAppServices, AuthorityRouteGroup


router = APIRouter(tags=[AuthorityRouteGroup.SUPERVISOR])


@router.get("/health", response_model=None)
def health(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Return process-level authority app health."""

    return {
        **_operational_base(services),
        "status": "ok",
        "ready": services.readiness_report.ready,
    }


@router.get("/live", response_model=None)
def live(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Return liveness without probing persistence."""

    return {
        **_operational_base(services),
        "live": True,
    }


@router.get("/ready", response_model=None)
def ready(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Return protocol-compatible readiness details."""

    return services.readiness_report.to_dict()


@router.get("/version", response_model=None)
def version(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Return protocol and schema compatibility details."""

    return services.version_report.to_dict()


@router.get("/capabilities", response_model=None)
def capabilities(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Return authority backend capability facts."""

    return services.capabilities.to_dict()


def _operational_base(services: AuthorityAppServices) -> dict[str, PlainData]:
    return {
        "protocol_version": AUTHORITY_PROTOCOL_VERSION,
        "service_generation": services.service_generation,
        "workspace_id": services.workspace_id,
        "readiness": services.readiness.value,
    }


__all__ = ["router"]
