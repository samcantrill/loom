"""Authority mutation route ownership boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from loom.pipeline.stores import AUTHORITY_PROTOCOL_VERSION
from loom.serialization import PlainData

from ..dependencies import get_authority_services
from ..services import AuthorityAppServices, AuthorityRouteGroup


MUTATION_ROUTE_PREFIX = "/v1/authority"

router = APIRouter(prefix=MUTATION_ROUTE_PREFIX, tags=[AuthorityRouteGroup.MUTATION])


@router.get("", response_model=None)
def route_group_manifest(
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Describe the reserved mutation route group without mutating state."""

    return {
        "protocol_version": AUTHORITY_PROTOCOL_VERSION,
        "route_group": AuthorityRouteGroup.MUTATION.value,
        "service_generation": services.service_generation,
        "workspace_id": services.workspace_id,
        "mutation_routes_implemented": False,
        "operations": [],
    }


__all__ = [
    "MUTATION_ROUTE_PREFIX",
    "router",
]
