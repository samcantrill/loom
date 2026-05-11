"""Authority mutation route ownership boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from loom.pipeline.stores import (
    AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH,
    AUTHORITY_MUTATION_OPEN_RUN_PATH,
    AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH,
    AUTHORITY_MUTATION_ROUTE_PREFIX,
    AUTHORITY_MUTATION_RUN_ADMIT_PATH,
    AUTHORITY_MUTATION_RUN_TRANSITION_PATH,
    AUTHORITY_MUTATION_STAGE_TRANSITION_PATH,
    AUTHORITY_PROTOCOL_VERSION,
)
from loom.serialization import PlainData

from ..dependencies import get_authority_services
from ..mutation_service import (
    AuthorityMutationOperation,
    unsupported_mutation_response,
)
from ..services import AuthorityAppServices, AuthorityRouteGroup


MUTATION_ROUTE_PREFIX = AUTHORITY_MUTATION_ROUTE_PREFIX

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
        "mutation_routes_implemented": services.mutation_service is not None,
        "operations": [
            operation.value for operation in AuthorityMutationOperation
        ]
        if services.mutation_service is not None
        else [],
    }


@router.post(
    AUTHORITY_MUTATION_RUN_ADMIT_PATH.removeprefix(MUTATION_ROUTE_PREFIX),
    response_model=None,
)
def admit_run(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Admit a run through the configured mutation service."""

    return _handle(AuthorityMutationOperation.ADMIT_RUN, payload, services)


@router.post(
    AUTHORITY_MUTATION_OPEN_RUN_PATH.removeprefix(MUTATION_ROUTE_PREFIX),
    response_model=None,
)
def open_run(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Read a run snapshot through the configured mutation service."""

    return _handle(AuthorityMutationOperation.OPEN_RUN, payload, services)


@router.post(
    AUTHORITY_MUTATION_RUN_TRANSITION_PATH.removeprefix(MUTATION_ROUTE_PREFIX),
    response_model=None,
)
def transition_run(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Apply a run status transition."""

    return _handle(AuthorityMutationOperation.TRANSITION_RUN, payload, services)


@router.post("/runs/leases/acquire", response_model=None)
def acquire_controller_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Acquire a run controller lease."""

    return _handle(
        AuthorityMutationOperation.ACQUIRE_CONTROLLER_LEASE,
        payload,
        services,
    )


@router.post("/runs/leases/renew", response_model=None)
def renew_controller_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Renew a run controller lease."""

    return _handle(
        AuthorityMutationOperation.RENEW_CONTROLLER_LEASE,
        payload,
        services,
    )


@router.post("/runs/leases/release", response_model=None)
def release_controller_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Release a run controller lease."""

    return _handle(
        AuthorityMutationOperation.RELEASE_CONTROLLER_LEASE,
        payload,
        services,
    )


@router.post("/runs/leases/fail", response_model=None)
def fail_controller_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Fail a run controller lease."""

    return _handle(AuthorityMutationOperation.FAIL_CONTROLLER_LEASE, payload, services)


@router.post("/runs/submitted/write", response_model=None)
def write_submitted_operation(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Persist a submitted-operation summary."""

    return _handle(
        AuthorityMutationOperation.WRITE_SUBMITTED_OPERATION,
        payload,
        services,
    )


@router.post("/runs/submitted/read", response_model=None)
def read_submitted_operation(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Read a submitted-operation summary."""

    return _handle(
        AuthorityMutationOperation.READ_SUBMITTED_OPERATION,
        payload,
        services,
    )


@router.post("/runs/submitted/list", response_model=None)
def list_submitted_operations(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """List submitted-operation summaries for a run."""

    return _handle(
        AuthorityMutationOperation.LIST_SUBMITTED_OPERATIONS,
        payload,
        services,
    )


@router.post(
    AUTHORITY_MUTATION_STAGE_TRANSITION_PATH.removeprefix(MUTATION_ROUTE_PREFIX),
    response_model=None,
)
def transition_stage(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Apply a stage status transition."""

    return _handle(AuthorityMutationOperation.TRANSITION_STAGE, payload, services)


@router.post(
    AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH.removeprefix(
        MUTATION_ROUTE_PREFIX
    ),
    response_model=None,
)
def allocate_stage_attempt(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Allocate a stage attempt and optional stage lease."""

    return _handle(
        AuthorityMutationOperation.ALLOCATE_STAGE_ATTEMPT,
        payload,
        services,
    )


@router.post("/stages/leases/renew", response_model=None)
def renew_stage_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Renew a stage lease."""

    return _handle(AuthorityMutationOperation.RENEW_STAGE_LEASE, payload, services)


@router.post("/stages/leases/release", response_model=None)
def release_stage_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Release a stage lease."""

    return _handle(AuthorityMutationOperation.RELEASE_STAGE_LEASE, payload, services)


@router.post("/stages/leases/fail", response_model=None)
def fail_stage_lease(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Fail a stage lease."""

    return _handle(AuthorityMutationOperation.FAIL_STAGE_LEASE, payload, services)


@router.post("/stages/attempts/finish", response_model=None)
def finish_stage_attempt(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Record a terminal stage attempt state."""

    return _handle(
        AuthorityMutationOperation.FINISH_STAGE_ATTEMPT,
        payload,
        services,
    )


@router.post(
    AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH.removeprefix(
        MUTATION_ROUTE_PREFIX
    ),
    response_model=None,
)
def record_output_commit(
    payload: dict[str, object],
    services: AuthorityAppServices = Depends(get_authority_services),
) -> dict[str, PlainData]:
    """Record a fenced stage output commit."""

    return _handle(
        AuthorityMutationOperation.RECORD_OUTPUT_COMMIT,
        payload,
        services,
    )


def _handle(
    operation: AuthorityMutationOperation,
    payload: dict[str, object],
    services: AuthorityAppServices,
) -> dict[str, PlainData]:
    service = services.mutation_service
    if service is None:
        return unsupported_mutation_response(
            operation,
            payload,
            service_generation=services.service_generation,
            workspace_id=services.workspace_id,
        ).to_dict()
    return service.handle(operation, payload).to_dict()


__all__ = [
    "MUTATION_ROUTE_PREFIX",
    "router",
]
