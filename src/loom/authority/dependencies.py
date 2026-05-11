"""FastAPI dependency accessors for authority routes."""

from __future__ import annotations

from fastapi import Request

from .services import AuthorityAppServices


def get_authority_services(request: Request) -> AuthorityAppServices:
    """Return the authority service dependency container for a request."""

    services = getattr(request.app.state, "authority_services", None)
    if not isinstance(services, AuthorityAppServices):
        raise RuntimeError("authority services are not configured on the app")
    return services


__all__ = ["get_authority_services"]
