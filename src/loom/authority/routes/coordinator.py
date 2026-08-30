"""Explicit least-privilege coordinator authority routes."""

from __future__ import annotations

from collections.abc import Callable
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request

from loom.pipeline.stores.coordinator_authority import (
    COORDINATOR_AUTHORITY_ROUTE_PREFIX,
    COORDINATOR_AUTHORITY_SERVICE_HEADER,
)
from loom.serialization import PlainData

from ..dependencies import get_authority_services
from ..mutation_service import (
    AuthorityMutationOperation,
    unsupported_mutation_response,
)
from ..services import (
    AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY,
    AuthorityAppServices,
    AuthorityRouteGroup,
)


router = APIRouter(
    prefix=COORDINATOR_AUTHORITY_ROUTE_PREFIX,
    tags=[AuthorityRouteGroup.COORDINATOR],
)

_ROUTES = {
    "/runs/open": AuthorityMutationOperation.COORDINATOR_OPEN_RUN,
    "/runs/transition": AuthorityMutationOperation.COORDINATOR_TRANSITION_RUN,
    "/stages/transition": AuthorityMutationOperation.COORDINATOR_TRANSITION_STAGE,
    "/admissions/bind": AuthorityMutationOperation.BIND_COORDINATOR_ADMISSION,
    "/cancellation/install": AuthorityMutationOperation.INSTALL_CANCELLATION_EPOCH,
    "/cancellation/read": AuthorityMutationOperation.READ_CANCELLATION_EPOCH,
    "/cancellation/finalize": AuthorityMutationOperation.FINALIZE_CANCELLATION,
    "/attempts/prepare": AuthorityMutationOperation.ENSURE_PREPARED_ATTEMPT,
    "/attempts/bind": AuthorityMutationOperation.BIND_PREPARED_ATTEMPT,
    "/attempts/unbind": AuthorityMutationOperation.UNBIND_PREPARED_ATTEMPT,
    "/attempts/grant": AuthorityMutationOperation.GRANT_PREPARED_ATTEMPT,
    "/attempts/start": AuthorityMutationOperation.CONFIRM_EXECUTION_STARTED,
    "/attempts/terminal": AuthorityMutationOperation.RECORD_MANAGED_TERMINAL,
    "/attempts/recovery-close": AuthorityMutationOperation.CLOSE_MANAGED_FENCE,
    "/attempts/output-commit": AuthorityMutationOperation.RECORD_MANAGED_OUTPUT,
    "/reliability/policies/write": AuthorityMutationOperation.WRITE_RELIABILITY_POLICY,
    "/reliability/policies/list": AuthorityMutationOperation.LIST_RELIABILITY_POLICIES,
    "/reliability/statuses/write": AuthorityMutationOperation.WRITE_RELIABILITY_STATUS,
    "/reliability/statuses/list": AuthorityMutationOperation.LIST_RELIABILITY_STATUSES,
    "/reliability/transactions/write": AuthorityMutationOperation.WRITE_ATTEMPT_TRANSACTION,
    "/reliability/transactions/chain": AuthorityMutationOperation.READ_TRANSACTION_CHAIN,
    "/reliability/transactions/list": AuthorityMutationOperation.LIST_ATTEMPT_TRANSACTIONS,
    "/reliability/retries/write": AuthorityMutationOperation.WRITE_RETRY_DECISION,
    "/reliability/retries/list": AuthorityMutationOperation.LIST_RETRY_DECISIONS,
    "/reliability/timeouts/write": AuthorityMutationOperation.WRITE_TIMEOUT_OUTCOME,
    "/reliability/timeouts/list": AuthorityMutationOperation.LIST_TIMEOUT_OUTCOMES,
}


def _endpoint(
    operation: AuthorityMutationOperation,
) -> Callable[..., dict[str, PlainData]]:
    def apply(
        payload: dict[str, object],
        request: Request,
        services: AuthorityAppServices = Depends(get_authority_services),
    ) -> dict[str, PlainData]:
        _require_coordinator_principal(request, services)
        service = services.mutation_service
        if service is None:
            return unsupported_mutation_response(
                operation,
                payload,
                service_generation=services.service_generation,
                workspace_id=services.workspace_id,
            ).to_dict()
        return service.handle(operation, payload).to_dict()

    apply.__name__ = operation.value
    apply.__doc__ = f"Apply the {operation.value} coordinator authority operation."
    return apply


def _require_coordinator_principal(
    request: Request, services: AuthorityAppServices
) -> None:
    """Bind the application service ID to the verified mTLS peer certificate."""

    credentials = services.coordinator_credentials
    if credentials is None:
        # Explicit in-process composition is already inside the trusted owner.
        return
    service_id = request.headers.get(COORDINATOR_AUTHORITY_SERVICE_HEADER)
    peer_fingerprint = getattr(
        request.state,
        AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY,
        None,
    )
    expected = None if service_id is None else credentials.get(service_id)
    if (
        expected is None
        or not isinstance(peer_fingerprint, str)
        or not hmac.compare_digest(expected, peer_fingerprint)
    ):
        raise HTTPException(
            status_code=403,
            detail="coordinator authority principal is not authorized",
        )


for _path, _operation in _ROUTES.items():
    router.add_api_route(
        _path,
        _endpoint(_operation),
        methods=["POST"],
        response_model=None,
    )


__all__ = ["router"]
