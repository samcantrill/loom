"""FastAPI application factory for the Loom authority service."""

from __future__ import annotations

from fastapi import FastAPI

from loom import __version__

from .routes import mutations, supervisor
from .services import (
    AUTHORITY_SERVICES_STATE_KEY,
    AuthorityAppServices,
    default_authority_services,
)


def create_authority_app(
    *,
    services: AuthorityAppServices | None = None,
    title: str = "Loom Authority",
) -> FastAPI:
    """Create an in-process constructable authority FastAPI app."""

    app = FastAPI(title=title, version=__version__)
    setattr(
        app.state,
        AUTHORITY_SERVICES_STATE_KEY,
        services if services is not None else default_authority_services(),
    )
    app.include_router(supervisor.router)
    app.include_router(mutations.router)
    return app


__all__ = [
    "AUTHORITY_SERVICES_STATE_KEY",
    "create_authority_app",
]
